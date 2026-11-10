import json
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiResult,
    AiToolCall,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.application.ports.agent_activity_publisher import AgentActivityCode
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.execution.plan_executor import PlanExecutor, _missing_expected_actions
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.domain.exceptions import (
    AgentAmbiguousClassException,
    AgentToolArgumentsException,
    AgentToolLimitException,
    UnsupportedAgentToolActionException,
)
from app.modules.assistant.application.services.execution.terminal_failure import (
    DomainFailureCategory,
)
from app.modules.diagram.domain.exceptions import (
    DiagramAttributeNotFoundException,
    DiagramClassIdConflictException,
    DiagramClassNameAlreadyExistsException,
    DiagramClassNotFoundException,
    DiagramRelationNotFoundException,
    PrimaryKeyCannotBeDeletedException,
)
from tests.modules.assistant.agent_test_helpers import (
    CountingAiProvider,
    CountingToolRegistry,
)


def _context(prompt="Crea Producto"):
    return AgentContext(
        user_id="u1",
        project_id=uuid4(),
        instructions="instructions",
        prompt=prompt,
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=100,
        requires_compaction=False,
    )


class SequenceProvider:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.results.pop(0)


def _tool(name="apply_diagram_changes"):
    return AiToolDefinition(
        name=name,
        description="Aplica cambios.",
        parameters={"type": "object", "additionalProperties": False},
    )


def test_operation_checklist_requires_the_named_target():
    ledger = [
        {"task_id": "classes", "status": "applied", "action_kind": "CREATE_CLASS", "target_name": "Producto"},
        {"task_id": "classes", "status": "applied", "action_kind": "CREATE_CLASS", "target_name": "Casa"},
    ]
    expected = [
        {"kind": "CREATE_CLASS", "name": "Producto"},
        {"kind": "CREATE_CLASS", "name": "Categoria"},
    ]
    assert _missing_expected_actions(expected, ledger, "classes") == [expected[1]]


@pytest.mark.anyio
async def test_direct_request_calls_registered_tool_and_reports_persistable_progress():
    call = AiToolCall(id="call-1", name="apply_diagram_changes", arguments={"actions": []})
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(call,)),
            AiResult(text="Creé Producto.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    async def mutate(arguments, report):
        await report(
            {
                "operation_id": "operation-1",
                "action_kind": "CREATE_CLASS",
                "status": "validated",
            }
        )
        await report(
            {
                "operation_id": "operation-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "class-1"}],
            }
        )
        return {"results": [{"status": "applied"}], "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate))
    progress = []
    executor = PlanExecutor(provider, registry, max_tool_calls=3)

    async def save(plan):
        progress.append(plan.to_dict())

    result = await executor.execute(_context(), None, save)

    assert result.completed is True
    assert result.text == "Creé Producto."
    assert progress[-1]["operation_ledger"][0]["status"] == "applied"
    assert progress[-1]["operation_ledger"][0]["entity_refs"] == [
        {"type": "class", "id": "class-1"}
    ]


@pytest.mark.anyio
async def test_batched_task_waits_for_every_expected_operation():
    provider = SequenceProvider([
        AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(
            AiToolCall(id="first", name="apply_diagram_changes", arguments={"actions": []}),
        )),
        AiResult(text="Listo.", model_role=ModelRole.MAIN, model="qwen"),
        AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(
            AiToolCall(id="second", name="apply_diagram_changes", arguments={"actions": []}),
        )),
        AiResult(text="Ahora sí.", model_role=ModelRole.MAIN, model="qwen"),
    ])
    registry = ToolRegistry()
    applied = 0

    async def mutate(arguments, report):
        nonlocal applied
        applied += 1
        await report({
            "operation_id": f"create-{applied}", "action_kind": "CREATE_CLASS",
            "status": "applied", "entity_refs": [{"type": "class", "id": f"class-{applied}"}],
        })
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate))
    plan = ExecutionPlan.create(goal="Crear dos clases", tasks=[{
        "id": "classes", "objective": "Crea Producto y Categoria", "kind": "mutation",
        "depends_on": [], "expected_actions": ["CREATE_CLASS", "CREATE_CLASS"],
    }])
    response, calls_used, completed = await PlanExecutor(
        provider, registry, max_tool_calls=4,
    )._run_task(
        context=_context("Crea Producto y Categoria"), objective=plan.tasks[0]["objective"],
        requires_mutation=True, task_id="classes", plan=plan, tool_calls_used=0,
        on_progress=None, on_activity=None, dependency_results=None,
        confirmed_tool_results=[], include_visual_context=False,
    )
    assert completed is True
    assert response == "Ahora sí."
    assert calls_used == 2
    assert applied == 2
    assert "Faltan operaciones" in provider.requests[2].messages[-1].content


@pytest.mark.anyio
async def test_expected_operation_gets_one_correction_when_model_stops_without_tools():
    provider = SequenceProvider([
        AiResult(text="Listo.", model_role=ModelRole.MAIN, model="qwen"),
        AiResult(
            text="", model_role=ModelRole.MAIN, model="qwen",
            tool_calls=(AiToolCall(
                id="create", name="apply_diagram_changes", arguments={"actions": []},
            ),),
        ),
        AiResult(text="Creada.", model_role=ModelRole.MAIN, model="qwen"),
    ])
    registry = ToolRegistry()

    async def mutate(arguments, report):
        await report({
            "operation_id": "create", "action_kind": "CREATE_CLASS",
            "target_name": "Producto", "status": "applied",
            "entity_refs": [{"type": "class", "id": "class-1"}],
        })
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate))
    plan = ExecutionPlan.create(goal="Crear Producto", tasks=[{
        "id": "classes", "objective": "Crea Producto", "kind": "mutation",
        "depends_on": [], "expected_actions": [{"kind": "CREATE_CLASS", "name": "Producto"}],
    }])
    response, calls_used, completed = await PlanExecutor(
        provider, registry, max_tool_calls=3,
    )._run_task(
        context=_context(), objective="Crea Producto", requires_mutation=True,
        task_id="classes", plan=plan, tool_calls_used=0, on_progress=None,
        on_activity=None, dependency_results=None, confirmed_tool_results=[],
        include_visual_context=False,
    )
    assert completed is True
    assert calls_used == 1
    assert response == "Creada."
    assert "Faltan operaciones" in provider.requests[1].messages[-1].content


@pytest.mark.anyio
async def test_executor_does_not_inject_memory_in_task_context():
    provider = SequenceProvider(
        [AiResult(text="Listo.", model_role=ModelRole.MAIN, model="qwen")]
    )
    memory = "m" * 9_000 + "final-memory-marker"
    context = replace(_context("Analiza Producto"), summary_context=memory)

    await PlanExecutor(provider, ToolRegistry()).execute(context, None)

    for msg in provider.requests[0].messages:
        assert "final-memory-marker" not in msg.content


@pytest.mark.anyio
async def test_executor_lets_model_correct_invalid_ids_before_mutating():
    class_id = str(uuid4())
    invalid_call = AiToolCall(
        "invalid-create",
        "apply_diagram_changes",
        {
            "actions": [
                {"operation_id": "class", "kind": "CREATE_CLASS", "name": "Casa"},
                {
                    "operation_id": "attribute",
                    "kind": "CREATE_ATTRIBUTE",
                    "class_id": None,
                    "name": "puerta",
                },
            ]
        },
    )
    create_class_call = AiToolCall(
        "create-class",
        "apply_diagram_changes",
        {"actions": [{"operation_id": "class", "kind": "CREATE_CLASS", "name": "Casa"}]},
    )
    create_attribute_call = AiToolCall(
        "create-attribute",
        "apply_diagram_changes",
        {
            "actions": [
                {
                    "operation_id": "attribute",
                    "kind": "CREATE_ATTRIBUTE",
                    "class_id": class_id,
                    "name": "puerta",
                }
            ]
        },
    )
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(invalid_call,)),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(create_class_call,),
            ),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(create_attribute_call,),
            ),
            AiResult(text="Listo.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    applied = []

    async def mutate(arguments, report):
        actions = arguments["actions"]
        if any(
            "class_id" in action and action["class_id"] is None
            for action in actions
        ):
            raise AgentToolArgumentsException()
        action = actions[0]
        applied.append(action["kind"])
        refs = (
            [{"type": "class", "id": class_id}]
            if action["kind"] == "CREATE_CLASS"
            else [{"type": "attribute", "id": str(uuid4())}]
        )
        await report(
            {
                "operation_id": action["operation_id"],
                "action_kind": action["kind"],
                "status": "applied",
                "entity_refs": refs,
            }
        )
        return {
            "status": "applied",
            "results": [{"status": "applied", "entity_refs": refs}],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool(), mutate, mutating=True))

    result = await PlanExecutor(provider, registry).execute(_context(), None)

    assert result.completed is True
    assert result.text == "Listo."
    assert applied == ["CREATE_CLASS", "CREATE_ATTRIBUTE"]
    correction_message = provider.requests[1].messages[-1]
    assert isinstance(correction_message.content, str)
    assert "entity_refs.id" in correction_message.content
    class_result_message = provider.requests[2].messages[-1]
    assert isinstance(class_result_message.content, str)
    assert class_id in class_result_message.content


@pytest.mark.anyio
async def test_executor_reports_read_and_mutation_kinds_without_tool_arguments():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "read-1",
                        "search_diagram_elements",
                        {"query": "Producto", "types": ["class"]},
                    ),
                ),
            ),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "mutate-1",
                        "apply_diagram_changes",
                        {"actions": [{"kind": "CREATE_CLASS", "name": "Producto"}]},
                    ),
                ),
            ),
            AiResult(text="Listo.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    async def search(_arguments, _report):
        return {"items": []}

    async def mutate(_arguments, report):
        await report({"action_kind": "CREATE_CLASS", "status": "validated"})
        await report({"action_kind": "CREATE_CLASS", "status": "applied"})
        return {"results": [{"status": "applied"}], "mutation_applied": True}

    registry.register(RegisteredTool(_tool("search_diagram_elements"), search))
    registry.register(RegisteredTool(_tool(), mutate, mutating=True))
    activities = []

    async def report_activity(code):
        activities.append(code)

    result = await PlanExecutor(provider, registry).execute(
        _context(), None, on_activity=report_activity
    )

    assert result.completed is True
    assert activities == [
        AgentActivityCode.READING_CLASSES,
        AgentActivityCode.CREATING_CLASS,
    ]


@pytest.mark.anyio
async def test_dependent_task_waits_for_previous_task_and_synthesizes_summary():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-a", "apply_diagram_changes", {"actions": []}),),
            ),
            AiResult(text="A lista.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-b", "apply_diagram_changes", {"actions": []}),),
            ),
            AiResult(text="B lista.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="Se crearon A y B.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    plan = ExecutionPlan.create(
        goal="Crear objetos relacionados",
        tasks=[
            {"id": "first", "objective": "Crear A", "kind": "mutation"},
            {
                "id": "second",
                "objective": "Crear B",
                "kind": "mutation",
                "depends_on": ["first"],
            },
        ],
    )
    registry = ToolRegistry()

    async def mutate(_arguments, _report):
        return {"results": [{"status": "applied"}], "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate))
    result = await PlanExecutor(provider, registry).execute(
        _context("Crea A y B"), plan
    )
    assert result.completed is True
    assert result.text == "Se crearon A y B."
    assert len(provider.requests) == 5
    assert provider.requests[-1].tools == ()


@pytest.mark.anyio
async def test_executor_orders_tasks_by_dependencies_before_starting_them():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-base", "apply_diagram_changes", {}),),
            ),
            AiResult(text="Base creada.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-dependent", "apply_diagram_changes", {}),),
            ),
            AiResult(text="Dependiente creado.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="Ambas clases creadas.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    plan = ExecutionPlan.create(
        goal="Crear clases dependientes",
        tasks=[
            {
                "id": "dependent",
                "objective": "Crear la clase dependiente",
                "kind": "mutation",
                "depends_on": ["base"],
            },
            {"id": "base", "objective": "Crear la clase base", "kind": "mutation"},
        ],
    )
    registry = ToolRegistry()

    async def mutate(_arguments, _report):
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate, mutating=True))

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is True
    assert plan.tasks[0]["id"] == "base"
    assert plan.tasks[1]["id"] == "dependent"
    assert "Crear la clase base" in provider.requests[0].messages[-1].content
    assert "Crear la clase dependiente" in provider.requests[2].messages[-1].content


@pytest.mark.anyio
async def test_dependent_task_receives_only_confirmed_tool_results_and_bridge_id():
    bridge_class_id = "confirmed-bridge-class-id"
    unconfirmed_class_id = "unconfirmed-class-id"
    relation_call = AiToolCall(
        "call-relation",
        "apply_diagram_changes",
        {"actions": [{"kind": "CREATE_RELATION"}]},
    )
    attribute_call = AiToolCall(
        "call-attribute",
        "apply_diagram_changes",
        {"actions": [{"kind": "CREATE_ATTRIBUTE", "class_id": bridge_class_id}]},
    )
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(relation_call,)),
            AiResult(text="Relación creada.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(attribute_call,)),
            AiResult(text="Atributo creado.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="Se creó la relación y su atributo.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    plan = ExecutionPlan.create(
        goal="Crear relación y atributo de puente",
        tasks=[
            {"id": "relation", "objective": "Crear relación N:M", "kind": "mutation"},
            {
                "id": "bridge-attribute",
                "objective": "Agregar cantidad a la clase puente",
                "kind": "mutation",
                "depends_on": ["relation"],
            },
        ],
    )
    registry = ToolRegistry()
    mutation_arguments = []

    async def mutate(arguments, report):
        mutation_arguments.append(arguments)
        if len(mutation_arguments) == 1:
            await report(
                {
                    "operation_id": "relation-operation",
                    "action_kind": "CREATE_RELATION",
                    "status": "applied",
                    "entity_refs": [{"type": "class", "id": bridge_class_id}],
                    "derived_effects": [{"type": "class", "id": bridge_class_id}],
                }
            )
            return {
                "status": "applied",
                "mutation_applied": True,
                "results": [
                    {
                        "operation_id": "relation-operation",
                        "status": "applied",
                        "entity_refs": [{"type": "class", "id": bridge_class_id}],
                        "derived_effects": [{"type": "class", "id": bridge_class_id}],
                    },
                    {
                        "operation_id": "proposal-only",
                        "status": "validated",
                        "entity_refs": [{"type": "class", "id": unconfirmed_class_id}],
                    },
                ],
            }
        assert arguments["actions"][0]["class_id"] == bridge_class_id
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate, mutating=True))

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    dependency_message = next(
        message.content
        for message in provider.requests[2].messages
        if "Resultados confirmados de tareas prerequisito" in message.content
    )
    assert result.completed is True
    assert bridge_class_id in dependency_message
    assert unconfirmed_class_id not in dependency_message
    assert "JSON no confiable" in dependency_message
    assert mutation_arguments[1]["actions"][0]["class_id"] == bridge_class_id


@pytest.mark.anyio
async def test_bridge_attribute_resolution_via_relation_detail_without_ambiguous_search():
    """US2: Tarea dependiente recupera puente mediante get_diagram_element sobre relación confirmada."""
    relation_id = "confirmed-rel-123"
    bridge_class_id = "confirmed-bridge-456"

    # Secuencia de IA:
    # 1. Tarea 1: crear relación N:M -> llamada apply_diagram_changes
    # 2. Tarea 1: fin de tarea
    # 3. Tarea 2: consultar detalle de la relación -> get_diagram_element
    # 4. Tarea 2: aplicar atributo al bridge_class_id -> apply_diagram_changes
    # 5. Tarea 2: fin de tarea
    # 6. Síntesis final
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-rel",
                        "apply_diagram_changes",
                        {"actions": [{"kind": "CREATE_RELATION"}]},
                    ),
                ),
            ),
            AiResult(text="Relación N:M creada.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-get-rel",
                        "get_diagram_element",
                        {"type": "relation", "id": relation_id},
                    ),
                ),
            ),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-add-attr",
                        "apply_diagram_changes",
                        {
                            "actions": [
                                {
                                    "operation_id": "op-bridge-attr",
                                    "kind": "CREATE_ATTRIBUTE",
                                    "class_id": bridge_class_id,
                                    "name": "calificacion",
                                }
                            ]
                        },
                    ),
                ),
            ),
            AiResult(text="Atributo agregado a la clase puente.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="Plan completado con éxito.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()
    search_called = []
    applied_mutations = []

    async def mock_search(_arguments, _report=None):
        search_called.append(True)
        return {"items": [], "status": "ok"}

    async def mock_get(arguments, _report=None):
        assert arguments["type"] == "relation"
        assert arguments["id"] == relation_id
        return {
            "type": "relation",
            "id": relation_id,
            "name": "EstudianteCurso",
            "detail": {
                "relation_type": "ASSOCIATION",
                "bridge_class_id": bridge_class_id,
                "materialization": {
                    "bridge_class_id": bridge_class_id,
                    "derived_attributes": [],
                },
            },
        }

    async def mock_mutate(arguments, report):
        applied_mutations.append(arguments)
        actions = arguments["actions"]
        if actions[0]["kind"] == "CREATE_RELATION":
            await report({
                "operation_id": "op-rel",
                "action_kind": "CREATE_RELATION",
                "status": "applied",
                "entity_refs": [{"type": "relation", "id": relation_id}],
            })
            return {
                "status": "applied",
                "results": [
                    {
                        "operation_id": "op-rel",
                        "status": "applied",
                        "entity_refs": [{"type": "relation", "id": relation_id}],
                    }
                ],
                "mutation_applied": True,
            }
        # CREATE_ATTRIBUTE en la clase puente
        assert actions[0]["class_id"] == bridge_class_id
        await report({
            "operation_id": actions[0]["operation_id"],
            "action_kind": "CREATE_ATTRIBUTE",
            "status": "applied",
            "entity_refs": [{"type": "attribute", "id": "confirmed-attr-id"}],
        })
        return {
            "status": "applied",
            "results": [
                {
                    "operation_id": actions[0]["operation_id"],
                    "status": "applied",
                    "entity_refs": [{"type": "attribute", "id": "confirmed-attr-id"}],
                }
            ],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutate, mutating=True))
    registry.register(RegisteredTool(_tool("get_diagram_element"), mock_get, mutating=False))
    registry.register(RegisteredTool(_tool("search_diagram_elements"), mock_search, mutating=False))

    plan = ExecutionPlan.create(
        goal="Crear relación y añadir atributo a puente",
        tasks=[
            {"id": "t-rel", "objective": "Crear relación N:M", "kind": "mutation"},
            {
                "id": "t-attr",
                "objective": "Añadir atributo a clase puente",
                "kind": "mutation",
                "depends_on": ["t-rel"],
            },
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Crear N:M y atributo"), plan)

    assert result.completed is True
    assert plan.status == "completed"
    assert search_called == []  # Ninguna búsqueda ambigua ejecutada
    assert len(applied_mutations) == 2
    assert applied_mutations[1]["actions"][0]["class_id"] == bridge_class_id


@pytest.mark.anyio
async def test_rejected_tool_stops_plan_and_returns_incomplete_outcome():
    call = AiToolCall(id="call-1", name="apply_diagram_changes", arguments={})
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(call,)),
            AiResult(text="No hubo cambios.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    async def reject(_arguments, report):
        await report({"operation_id": "op-1", "status": "rejected", "error_code": "forbidden"})
        return {"status": "rejected", "error_code": "forbidden"}

    registry.register(RegisteredTool(_tool(), reject))
    result = await PlanExecutor(provider, registry).execute(_context(), None)

    assert result.completed is False
    assert len(provider.requests) == 2
    assert provider.requests[-1].tools == ()


@pytest.mark.anyio
async def test_visual_delete_action_is_rejected_before_any_batch_mutation_without_confirmation():
    call = AiToolCall(
        id="visual-delete",
        name="apply_diagram_changes",
        arguments={
            "actions": [
                {"operation_id": "create-first", "kind": "CREATE_CLASS", "name": "Nueva"},
                {"operation_id": "delete-second", "kind": "DELETE_CLASS", "class_id": str(uuid4())},
            ]
        },
    )
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(call,)),
            AiResult(text="No se pudo completar.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    calls = []

    async def mutate(arguments, _report):
        calls.append(arguments)
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate, mutating=True))
    progress = []
    result = await PlanExecutor(provider, registry).execute(
        replace(_context(), visual_mode="mutate", visual_context="{}", visual_needs_image=True),
        None,
        lambda plan: _save(progress, plan),
    )

    assert result.completed is False
    assert calls == []  # El lote completo se bloquea antes del CREATE_CLASS.
    assert any(
        operation.get("error_code") == "deletion_confirmation_required"
        for snapshot in progress
        for operation in snapshot.get("operation_ledger", [])
    )


@pytest.mark.anyio
async def test_independent_task_receives_no_visual_evidence_or_mutation_tools():
    provider = SequenceProvider(
        [
            AiResult(text="La respuesta independiente.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="La respuesta final.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("read_diagram"), lambda _args, _report: {}))
    registry.register(
        RegisteredTool(_tool("apply_diagram_changes"), lambda _args, _report: {}, mutating=True)
    )
    plan = ExecutionPlan.create(
        goal="Analizar imagen y contestar pregunta independiente",
        tasks=[
            {
                "id": "independent-answer",
                "objective": "Responde una pregunta textual independiente",
                "kind": "answer",
                "needs_image": False,
            }
        ],
    )
    context = replace(
        _context("Crea Producto y responde cuánto es 2+2"),
        visual_mode="mutate",
        visual_context='{"evidence":"VISUAL_SECRET"}',
        visual_allowed_elements={"classes": [{"name": "Producto", "attributes": []}]},
    )

    result = await PlanExecutor(provider, registry).execute(context, plan)

    assert result.completed
    assert all("VISUAL_SECRET" not in str(message.content) for message in provider.requests[0].messages)
    assert [tool.name for tool in provider.requests[0].tools] == ["read_diagram"]


@pytest.mark.anyio
async def test_visual_search_ambiguity_stops_before_mutation_and_requests_a_choice():
    first_id, second_id = str(uuid4()), str(uuid4())
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="fake",
                tool_calls=(AiToolCall("search", "search_diagram_elements", {"query": "Producto"}),),
            )
        ]
    )
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            _tool("search_diagram_elements"),
            lambda _args, _report: {
                "status": "ambiguous",
                "items": [
                    {"type": "class", "id": first_id, "name": "Producto"},
                    {"type": "class", "id": second_id, "name": "Producto"},
                ],
            },
        )
    )
    context = replace(
        _context("Crea Producto"),
        visual_mode="mutate",
        visual_needs_image=True,
        visual_context="{}",
        visual_allowed_elements={"classes": [{"name": "Producto", "attributes": []}], "relations": []},
    )

    result = await PlanExecutor(provider, registry).execute(context, None)

    assert result.metadata["kind"] == "visual_ambiguity"
    assert set(result.metadata["candidate_ids"]) == {first_id, second_id}
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_visual_ambiguity_preserves_earlier_confirmed_operations():
    first_id, second_id = str(uuid4()), str(uuid4())
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="fake",
                tool_calls=(AiToolCall("first", "apply_diagram_changes", {"action": "create"}),),
            ),
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="fake",
                tool_calls=(AiToolCall("second", "apply_diagram_changes", {"action": "ambiguous"}),),
            ),
        ]
    )
    registry = ToolRegistry()

    def validate_scope(arguments, _scope):
        if arguments["action"] == "ambiguous":
            raise AgentAmbiguousClassException("Producto", [first_id, second_id])

    async def apply(_arguments, report):
        await report({"operation_id": "first", "action_kind": "CREATE_CLASS", "status": "applied"})
        return {"status": "applied", "mutation_applied": True}

    registry.register(
        RegisteredTool(
            _tool(), apply, mutating=True, visual_scope_validator=validate_scope
        )
    )
    context = replace(
        _context("Crea las clases"),
        visual_mode="mutate",
        visual_needs_image=True,
        visual_context="{}",
        visual_allowed_elements={"classes": [], "relations": []},
    )

    result = await PlanExecutor(provider, registry).execute(context, None)

    assert result.metadata["kind"] == "visual_ambiguity"
    assert any(
        operation["operation_id"] == "first" and operation["status"] == "applied"
        for operation in result.metadata["prior_execution_plan"]["operation_ledger"]
    )


async def _save(progress, plan):
    progress.append(plan.to_dict())


@pytest.mark.anyio
async def test_direct_mutation_is_not_reported_complete_without_confirmed_tool_effect():
    provider = SequenceProvider(
        [
            AiResult(text="Ya creé Producto.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="No se confirmó ningún cambio.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    result = await PlanExecutor(provider, ToolRegistry()).execute(
        _context("Crea la clase Producto"), None
    )

    assert result.completed is False
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_simple_query_can_complete_without_mutation_tool():
    provider = SequenceProvider(
        [AiResult(text="El diagrama está vacío.", model_role=ModelRole.MAIN, model="qwen")]
    )

    result = await PlanExecutor(provider, ToolRegistry()).execute(
        _context("¿Qué ves en este proyecto?"), None
    )

    assert result.completed is True
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_answer_task_cannot_execute_mutating_tool():
    call = AiToolCall(id="call-mutate", name="apply_diagram_changes", arguments={"actions": []})
    provider = SequenceProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="qwen", tool_calls=(call,)),
            AiResult(text="La herramienta no estaba permitida.", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="No hubo cambios.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    executed = []

    async def mutate(_arguments, _report):
        executed.append(True)
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool(), mutate, mutating=True))
    plan = ExecutionPlan.create(
        goal="Responder sin cambios",
        tasks=[{"id": "answer", "objective": "Analiza el diagrama", "kind": "answer"}],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert executed == []
    assert provider.requests[0].tools == ()


@pytest.mark.anyio
async def test_tool_call_budget_stops_execution_with_controlled_failure():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall("call-1", "read_diagram", {}),
                    AiToolCall("call-2", "read_diagram", {}),
                ),
            ),
            AiResult(text="No se completó la consulta.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    executed = []

    async def read(_arguments, _report):
        executed.append(True)
        return {"status": "ok"}

    registry.register(RegisteredTool(_tool("read_diagram"), read))
    plan = ExecutionPlan.create(
        goal="Consulta acotada",
        tasks=[{"id": "answer", "objective": "Consulta", "kind": "answer"}],
    )

    result = await PlanExecutor(provider, registry, max_tool_calls=1).execute(
        _context("Describe el diagrama"), plan
    )

    assert result.completed is False
    assert len(executed) == 1
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_uncertain_tool_result_stops_without_retrying_the_operation():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("read-once", "read_diagram", {}),),
            ),
            AiResult(text="No pude confirmar la consulta.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()
    executions = []

    async def uncertain(_arguments, _report):
        executions.append(True)
        return {"status": "uncertain", "error_code": "uncertain_result"}

    registry.register(RegisteredTool(_tool("read_diagram"), uncertain))

    result = await PlanExecutor(provider, registry).execute(
        _context("Describe el diagrama"), None
    )

    assert result.completed is False
    assert executions == [True]
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_failure_synthesis_includes_confirmed_ledger_and_blocked_task():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-1", "apply_diagram_changes", {}),),
            ),
            AiResult(text="Falló después del primer cambio.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    async def partially_apply(_arguments, report):
        await report(
            {
                "operation_id": "committed-op",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "confirmed-class-id"}],
            }
        )
        return {
            "status": "rejected",
            "error_code": "forbidden",
            "results": [{"status": "applied"}, {"status": "rejected"}],
        }

    registry.register(RegisteredTool(_tool(), partially_apply))
    plan = ExecutionPlan.create(
        goal="Crear y revisar",
        tasks=[
            {"id": "mutate", "objective": "Crear la clase", "kind": "mutation"},
            {
                "id": "answer",
                "objective": "Responder qué quedó pendiente",
                "kind": "answer",
                "depends_on": ["mutate"],
            },
        ],
    )

    result = await PlanExecutor(provider, registry).execute(
        _context("Crea la clase y responde"), plan
    )

    synthesis_input = provider.requests[-1].messages[-1].content
    assert result.completed is False
    assert provider.requests[-1].enable_reasoning is False
    assert '"execution_plan"' not in synthesis_input
    assert '"operation_id":"committed-op"' in synthesis_input
    assert '"id":"confirmed-class-id"' in synthesis_input
    assert '"objective":"Responder qué quedó pendiente"' in synthesis_input
    assert '"status":"blocked"' in synthesis_input
    assert '"error_code":"forbidden"' in synthesis_input


@pytest.mark.anyio
async def test_tool_limit_synthesis_keeps_effects_from_active_task_and_blocks_remaining_work():
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall("call-1", "read_diagram", {}),
                    AiToolCall("call-2", "read_diagram", {}),
                ),
            ),
            AiResult(text="Se alcanzó el límite.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    async def read_once(_arguments, report):
        await report(
            {
                "operation_id": "read-committed",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "observed-class-id"}],
            }
        )
        return {"status": "ok"}

    registry.register(RegisteredTool(_tool("read_diagram"), read_once))
    plan = ExecutionPlan.create(
        goal="Consultar y resumir",
        tasks=[
            {"id": "read", "objective": "Leer la clase", "kind": "answer"},
            {
                "id": "final",
                "objective": "Resumir después de leer",
                "kind": "answer",
                "depends_on": ["read"],
            },
        ],
    )

    result = await PlanExecutor(provider, registry, max_tool_calls=1).execute(
        _context("Describe la clase y resume"), plan
    )

    synthesis_input = provider.requests[-1].messages[-1].content
    assert result.completed is False
    assert '"operation_id":"read-committed"' in synthesis_input
    assert '"id":"observed-class-id"' in synthesis_input
    assert '"objective":"Resumir después de leer"' in synthesis_input
    assert '"error_code":"limit_exceeded"' in synthesis_input
    assert '"status":"blocked"' in synthesis_input


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "failure", "max_arguments_chars", "expected_code"),
    [
        ("missing_tool", None, 12_000, "unsupported_action"),
        ("read_diagram", UnsupportedAgentToolActionException, 12_000, "unsupported_action"),
        ("read_diagram", AgentToolArgumentsException, 12_000, "invalid_arguments"),
        ("read_diagram", None, 1, "limit_exceeded"),
    ],
)
async def test_tool_failures_use_stable_contract_error_codes(
    tool_name, failure, max_arguments_chars, expected_code
):
    provider = SequenceProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-1", tool_name, {"value": "long"}),),
            ),
            AiResult(text="No se pudo completar.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry(max_arguments_chars=max_arguments_chars)
    if tool_name == "read_diagram":
        async def read(_arguments, _report):
            if failure is not None:
                raise failure()
            return {"status": "ok"}

        registry.register(RegisteredTool(_tool("read_diagram"), read))

    result = await PlanExecutor(provider, registry).execute(
        _context("Consulta esta clase"), None
    )

    synthesis_input = provider.requests[-1].messages[-1].content
    assert result.completed is False
    assert f'"error_code":"{expected_code}"' in synthesis_input
    assert "UNKNOWN_AGENT_TOOL" not in synthesis_input
    assert "INVALID_AGENT_TOOL_ARGUMENTS" not in synthesis_input
    assert "AGENT_TOOL_LIMIT_EXCEEDED" not in synthesis_input


@pytest.mark.anyio
async def test_plan_executor_independent_tasks_continue_when_one_branch_fails():
    """US1: Si una rama falla, sus descendientes se bloquean pero las tareas independientes continúan."""
    provider = SequenceProvider(
        [
            # Tarea 1: falla
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-1", "apply_diagram_changes", {}),),
            ),
            # Tarea 3 (independiente): éxito con llamada a tool y luego texto de fin de tarea
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-2", "apply_diagram_changes", {}),),
            ),
            AiResult(text="Tarea independiente ejecutada.", model_role=ModelRole.MAIN, model="qwen"),
            # Síntesis final
            AiResult(text="Se aplicó la tarea independiente; la rama dependiente falló.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()
    call_count = {"count": 0}

    async def dynamic_tool(arguments, report):
        call_count["count"] += 1
        if call_count["count"] == 1:
            # Primera llamada (rama fallida)
            return {"status": "rejected", "error_code": "forbidden", "results": [{"status": "rejected"}]}
        # Segunda llamada (tarea independiente)
        await report({
            "operation_id": "op-indep",
            "action_kind": "CREATE_CLASS",
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "indep-class-id"}],
        })
        return {
            "status": "applied",
            "results": [
                {
                    "operation_id": "op-indep",
                    "status": "applied",
                    "entity_refs": [{"type": "class", "id": "indep-class-id"}],
                }
            ],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), dynamic_tool))

    plan = ExecutionPlan.create(
        goal="Plan con ramas independientes y dependientes",
        tasks=[
            {"id": "branch-fail", "objective": "Tarea que falla", "kind": "mutation"},
            {"id": "branch-dep", "objective": "Tarea dependiente", "kind": "mutation", "depends_on": ["branch-fail"]},
            {"id": "branch-indep", "objective": "Tarea independiente", "kind": "mutation", "depends_on": []},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Ejecuta plan"), plan)

    # Verificaciones
    assert plan.get_task("branch-fail")["status"] == "failed"
    assert plan.get_task("branch-dep")["status"] == "blocked"
    assert plan.get_task("branch-indep")["status"] == "completed"
    assert result.completed is False
    assert plan.status == "partial"
    # El ledger contiene la operación de la tarea independiente aplicada
    applied_ops = [op for op in plan.operation_ledger if op.get("status") == "applied"]
    assert len(applied_ops) == 1
    assert applied_ops[0]["operation_id"] == "op-indep"


@pytest.mark.anyio
async def test_plan_executor_propagates_only_confirmed_refs_from_completed_dependencies():
    """US1: Solo referencias confirmadas de prerequisitos completados llegan a tareas posteriores."""
    provider = SequenceProvider(
        [
            # Tarea 1: éxito con class-a
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-1", "apply_diagram_changes", {}),),
            ),
            AiResult(text="Clase A creada.", model_role=ModelRole.MAIN, model="qwen"),
            # Tarea 2: dependiente de tarea 1
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(AiToolCall("call-2", "apply_diagram_changes", {"actions": [{"kind": "CREATE_ATTRIBUTE", "attr": "name"}]}),),
            ),
            AiResult(text="Atributo creado.", model_role=ModelRole.MAIN, model="qwen"),
            # Síntesis
            AiResult(text="Completado exitosamente.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()

    async def mock_mutation(arguments, report):
        if "attr" in json.dumps(arguments):
            await report({
                "operation_id": "op-attr-1",
                "action_kind": "CREATE_ATTRIBUTE",
                "status": "applied",
                "entity_refs": [{"type": "attribute", "id": "confirmed-attr-id"}],
            })
            return {
                "status": "applied",
                "results": [{"operation_id": "op-attr-1", "status": "applied", "entity_refs": [{"type": "attribute", "id": "confirmed-attr-id"}]}],
                "mutation_applied": True,
            }
        await report({
            "operation_id": "op-class-a",
            "action_kind": "CREATE_CLASS",
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "confirmed-a-id"}],
        })
        return {
            "status": "applied",
            "results": [
                {
                    "operation_id": "op-class-a",
                    "status": "applied",
                    "entity_refs": [{"type": "class", "id": "confirmed-a-id"}],
                }
            ],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutation))

    plan = ExecutionPlan.create(
        goal="Crear clase y luego atributo",
        tasks=[
            {"id": "t-class", "objective": "Crear clase A", "kind": "mutation"},
            {"id": "t-attr", "objective": "Crear atributo en clase A", "kind": "mutation", "depends_on": ["t-class"]},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Crea A y agrega atributo"), plan)

    assert result.completed is True
    assert plan.status == "completed"
    # El segundo llamado de tarea (requests[2]) recibió en el prompt los resultados confirmados de t-class
    second_task_request = provider.requests[2]
    task_2_prompt = second_task_request.messages[1].content
    assert "Resultados confirmados de tareas prerequisito" in task_2_prompt
    assert "confirmed-a-id" in task_2_prompt


@pytest.mark.anyio
async def test_plan_executor_pre_mutation_rejection_allows_correction_and_completes():
    """T024 [US4]: Error de argumentos previo a mutar solicita corrección y continúa exitosamente."""
    provider = SequenceProvider(
        [
            # Intento 1: llamada con class_id nulo
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-invalid",
                        "apply_diagram_changes",
                        {"actions": [{"kind": "CREATE_ATTRIBUTE", "class_id": None}]},
                    ),
                ),
            ),
            # Intento 2: modelo responde con argumentos corregidos
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-corrected",
                        "apply_diagram_changes",
                        {"actions": [{"kind": "CREATE_ATTRIBUTE", "class_id": "valid-cls-id"}]},
                    ),
                ),
            ),
            # Final de la tarea
            AiResult(text="Atributo creado con éxito.", model_role=ModelRole.MAIN, model="qwen"),
            # Síntesis
            AiResult(text="Solicitud procesada correctamente.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()

    async def mock_handler(arguments, report):
        action = arguments["actions"][0]
        if action.get("class_id") is None:
            raise AgentToolArgumentsException("class_id cannot be null")
        if report is not None:
            await report({
                "operation_id": "op-corr-1",
                "action_kind": "CREATE_ATTRIBUTE",
                "status": "applied",
                "entity_refs": [{"type": "attribute", "id": "attr-uuid-1"}],
            })
        return {
            "status": "applied",
            "results": [{"operation_id": "op-corr-1", "status": "applied", "entity_refs": [{"type": "attribute", "id": "attr-uuid-1"}]}],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_handler, mutating=True))

    plan = ExecutionPlan.create(
        goal="Crear atributo corrigiendo propuesta previa",
        tasks=[{"id": "t-attr", "objective": "Crear atributo", "kind": "mutation"}],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Crea atributo"), plan)

    assert result.completed is True
    assert plan.status == "completed"
    assert plan.get_task("t-attr")["status"] == "completed"

    # Verificar que el segundo request incluyó la respuesta con retryable y explicación de corrección
    second_request = provider.requests[1]
    tool_msg = next(m for m in second_request.messages if m.role == "tool")
    tool_content = json.loads(tool_msg.content)
    assert tool_content["status"] == "rejected"
    assert tool_content["retryable"] is True
    assert "Corrige los argumentos" in tool_content["correction"]
    assert "class_id cannot be null" in tool_content.get("detail", "")


@pytest.mark.anyio
async def test_plan_executor_correction_limit_exhausted_fails_and_blocks_dependents():
    """T024 [US4]: Cuando se agotan las correcciones (2 intentos), la tarea falla y bloquea descendientes."""
    invalid_call = AiResult(
        text="",
        model_role=ModelRole.MAIN,
        model="qwen",
        tool_calls=(
            AiToolCall(
                "call-bad",
                "apply_diagram_changes",
                {"actions": [{"kind": "CREATE_ATTRIBUTE", "class_id": None, "operation_id": "op-fail"}]},
            ),
        ),
    )

    provider = SequenceProvider(
        [
            invalid_call,  # Intento 1 -> corrección 1 solicitada
            invalid_call,  # Intento 2 -> corrección 2 solicitada
            invalid_call,  # Intento 3 -> límite excedido (> 2) -> falla controlada
            # Síntesis
            AiResult(text="No fue posible completar la solicitud.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()

    async def mock_handler(arguments, report):
        raise AgentToolArgumentsException("class_id cannot be null")

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_handler, mutating=True))

    plan = ExecutionPlan.create(
        goal="Tarea con límite de correcciones",
        tasks=[
            {"id": "t1-failing", "objective": "Crear atributo", "kind": "mutation"},
            {"id": "t2-dependent", "objective": "Crear relación dependiente", "kind": "mutation", "depends_on": ["t1-failing"]},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Intento"), plan)

    assert result.completed is False
    assert plan.status == "failed"
    assert plan.get_task("t1-failing")["status"] == "failed"
    assert plan.get_task("t1-failing")["error_code"] == "invalid_arguments"
    assert plan.get_task("t2-dependent")["status"] == "blocked"
    # El ledger registró la operación rechazada
    assert any(op.get("status") == "rejected" for op in plan.operation_ledger)


@pytest.mark.anyio
async def test_plan_executor_uncertainty_stops_immediately_without_retries():
    """T024 [US4]: Un resultado incierto no se reintenta y detiene la ejecución inmediatamente."""
    provider = SequenceProvider(
        [
            # Tarea 1: produce un resultado incierto
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall(
                        "call-unc",
                        "apply_diagram_changes",
                        {"actions": [{"kind": "CREATE_CLASS", "operation_id": "op-unc"}]},
                    ),
                ),
            ),
            # Síntesis (no hay llamada de corrección ni llamada para la tarea 2)
            AiResult(text="Error incierto durante commit.", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    registry = ToolRegistry()

    async def uncertain_handler(arguments, report):
        if report is not None:
            await report({
                "operation_id": "op-unc",
                "action_kind": "CREATE_CLASS",
                "status": "uncertain",
                "error_code": "uncertain_result",
            })
        return {
            "status": "uncertain",
            "results": [
                {
                    "operation_id": "op-unc",
                    "status": "uncertain",
                    "error_code": "uncertain_result",
                }
            ],
            "mutation_applied": False,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), uncertain_handler, mutating=True))

    plan = ExecutionPlan.create(
        goal="Manejo de incertidumbre",
        tasks=[
            {"id": "t1-unc", "objective": "Crear clase con fallo incierto", "kind": "mutation"},
            {"id": "t2-independent", "objective": "Tarea independiente posterior", "kind": "mutation", "depends_on": []},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context("Ejecuta"), plan)

    assert result.completed is False
    assert plan.status == "uncertain"
    assert plan.get_task("t1-unc")["status"] == "uncertain"
    # La tarea independiente T2 NUNCA se ejecutó (permaneció pending)
    assert plan.get_task("t2-independent")["status"] == "pending"
    # El proveedor solo recibió 2 llamadas (la tarea 1 y la síntesis final, sin reintentos ciegos)
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_plan_executor_direct_route_haz_equivalent_to_crea():
    applied = []

    async def mock_mutate(args, report):
        applied.append(args)
        if report:
            await report({
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "cls-1"}],
            })
        return {
            "status": "applied",
            "results": [{"operation_id": "op-1", "status": "applied", "entity_refs": [{"type": "class", "id": "cls-1"}]}],
            "mutation_applied": True,
        }

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutate, mutating=True))

    provider = SequenceProvider([
        AiResult(
            text="Creando clase Factura",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=[AiToolCall(id="tc-1", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Factura", "operation_id": "op-1"}]})],
        ),
        AiResult(text="Clase Factura creada.", model_role=ModelRole.MAIN, model="qwen"),
        AiResult(text="Listo, se creó la clase Factura.", model_role=ModelRole.MAIN, model="qwen"),
    ])

    result = await PlanExecutor(provider, registry).execute(_context("haz una clase Factura"), None)
    assert len(applied) == 1
    assert applied[0]["actions"][0]["kind"] == "CREATE_CLASS"
    assert applied[0]["actions"][0]["name"] == "Factura"


@pytest.mark.anyio
async def test_plan_executor_direct_route_negation_does_not_mutate():
    applied = []

    async def mock_mutate(args, report):
        applied.append(args)
        return {"status": "applied"}

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutate, mutating=True))

    provider = SequenceProvider([
        AiResult(text="Entendido, no crearé ninguna clase.", model_role=ModelRole.MAIN, model="qwen"),
        AiResult(text="Entendido, no crearé ninguna clase.", model_role=ModelRole.MAIN, model="qwen"),
    ])

    result = await PlanExecutor(provider, registry).execute(_context("no crees ninguna clase"), None)
    assert len(applied) == 0
    assert "no crearé" in result.text or "Entendido" in result.text


@pytest.mark.anyio
async def test_plan_executor_direct_route_ambiguity_requests_clarification():
    registry = ToolRegistry()
    provider = SequenceProvider([])

    result = await PlanExecutor(provider, registry).execute(_context("tal vez una clase o quizás modificarla"), None)
    assert "ambigua" in result.text
    assert "aclara" in result.text
    # No llamó al modelo ni a herramientas
    assert len(provider.requests) == 0


@pytest.mark.anyio
async def test_plan_executor_response_strips_internal_uuids():
    registry = ToolRegistry()

    async def mock_mutate(args, report):
        if report:
            await report({
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "11111111-2222-3333-4444-555555555555", "name": "Factura"}],
            })
        return {
            "status": "applied",
            "results": [{"operation_id": "op-1", "status": "applied", "entity_refs": [{"type": "class", "id": "11111111-2222-3333-4444-555555555555"}]}],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutate, mutating=True))

    uuid_str = "11111111-2222-3333-4444-555555555555"
    provider = SequenceProvider([
        AiResult(
            text="Creando Factura",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=[AiToolCall(id="tc-1", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Factura", "operation_id": "op-1"}]})],
        ),
        AiResult(
            text=f"Listo, creé la clase Factura (id: {uuid_str}).",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
    ])

    result = await PlanExecutor(provider, registry).execute(_context("crea una clase Factura"), None)
    # El UUID interno NO debe aparecer en la respuesta al usuario
    assert uuid_str not in result.text
    assert "Factura" in result.text


@pytest.mark.anyio
async def test_plan_executor_fallback_on_synthesis_error():
    registry = ToolRegistry()

    class FailingSynthesisProvider(SequenceProvider):
        async def complete(self, request):
            if request.purpose == "final_synthesis":
                raise RuntimeError("AI service down")
            return await super().complete(request)

    async def mock_mutate(args, report):
        if report:
            await report({
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "name": "Cliente"}],
            })
        return {
            "status": "applied",
            "results": [{"operation_id": "op-1", "status": "applied", "entity_refs": [{"type": "class", "name": "Cliente"}]}],
            "mutation_applied": True,
        }

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_mutate, mutating=True))

    plan = ExecutionPlan.create(
        goal="Crear clase",
        tasks=[{"id": "t1", "objective": "Crear Cliente", "kind": "mutation"}],
    )

    provider = FailingSynthesisProvider([
        AiResult(
            text="Creando Cliente",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=[AiToolCall(id="tc-1", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Cliente", "operation_id": "op-1"}]})],
        ),
        AiResult(text="Listo", model_role=ModelRole.MAIN, model="qwen"),
    ])

    result = await PlanExecutor(provider, registry).execute(_context("crea clase Cliente"), plan)
    # Debe haber usado el fallback determinista cordial sin romper
    assert "Cliente" in result.text
    assert "diagrama" in result.text


@pytest.mark.anyio
async def test_plan_executor_incomplete_relation_proposal_produces_clarification_and_no_mutation():
    """T013: Propuesta de relación incompleta (sin cardinalidades) produce aclaración final sin mutar."""
    from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
        DIAGRAM_MUTATION_TOOL,
        validate_actions,
    )

    registry = ToolRegistry()
    applied_mutations = []

    async def mock_mutate(args, report):
        validate_actions(args)
        applied_mutations.append(args)
        return {"status": "applied", "results": [], "mutation_applied": True}

    registry.register(RegisteredTool(DIAGRAM_MUTATION_TOOL, mock_mutate, mutating=True))

    invalid_relation_call = AiToolCall(
        id="call-invalid-rel",
        name="apply_diagram_changes",
        arguments={
            "actions": [
                {
                    "operation_id": "op-rel",
                    "kind": "CREATE_RELATION",
                    "relation_type": "ASSOCIATION",
                    "source_class_id": str(uuid4()),
                    "target_class_id": str(uuid4()),
                }
            ]
        },
    )

    provider = SequenceProvider([
        AiResult(
            text="Voy a conectar las entidades.",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(invalid_relation_call,),
        ),
        AiResult(
            text="Faltan las cardinalidades.",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
        AiResult(
            text="¿Qué cardinalidad corresponde al extremo de cada clase para crear la asociación?",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
    ])

    plan = ExecutionPlan.create(
        goal="Relacionar entidades",
        tasks=[{"id": "t1", "objective": "Relacionar Cliente y Pedido", "kind": "mutation"}],
    )

    result = await PlanExecutor(provider, registry).execute(
        _context("Relaciona Cliente y Pedido"),
        plan,
    )

    assert len(applied_mutations) == 0
    assert "cardinalidad" in result.text.lower()


@pytest.mark.anyio
async def test_plan_executor_contradictory_structural_proposal_rejects_and_clarifies():
    """T013: Propuesta estructural contradictoria (con cardinalidad prohibida) produce aclaración sin mutar."""
    from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
        DIAGRAM_MUTATION_TOOL,
        validate_actions,
    )

    registry = ToolRegistry()
    applied_mutations = []

    async def mock_mutate(args, report):
        validate_actions(args)
        applied_mutations.append(args)
        return {"status": "applied", "results": [], "mutation_applied": True}

    registry.register(RegisteredTool(DIAGRAM_MUTATION_TOOL, mock_mutate, mutating=True))

    invalid_comp_call = AiToolCall(
        id="call-invalid-comp",
        name="apply_diagram_changes",
        arguments={
            "actions": [
                {
                    "operation_id": "op-comp",
                    "kind": "CREATE_RELATION",
                    "relation_type": "COMPOSITION",
                    "source_class_id": str(uuid4()),
                    "target_class_id": str(uuid4()),
                    "source_cardinality": "1",
                }
            ]
        },
    )

    provider = SequenceProvider([
        AiResult(
            text="Creando composición.",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(invalid_comp_call,),
        ),
        AiResult(
            text="Composición no lleva cardinalidad.",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
        AiResult(
            text="Las relaciones de composición no llevan cardinalidad. Por favor aclara cuál es el todo y cuál la parte.",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
    ])

    plan = ExecutionPlan.create(
        goal="Componer entidades",
        tasks=[{"id": "t1", "objective": "Componer Casa y Habitación", "kind": "mutation"}],
    )

    result = await PlanExecutor(provider, registry).execute(
        _context("Compón Casa de Habitación"),
        plan,
    )

    assert len(applied_mutations) == 0
    assert "cardinalidad" in result.text.lower() or "todo" in result.text.lower()


@pytest.mark.anyio
async def test_terminal_class_not_found_stops_execution_and_blocks_descendants_and_independent():
    # T007: Clase ausente en mutación detiene el plan, falla la tarea actual,
    # bloquea descendientes e impide tareas independientes pendientes sin llamar al modelo.
    t1_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "RENAME_CLASS", "name": "Factura"}]},
    )
    provider = SequenceProvider([
        AiResult(
            text="Renombrando Factura",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(t1_call,),
        )
    ])

    registry = ToolRegistry()

    async def fail_tool(_arguments, _report=None):
        raise DiagramClassNotFoundException()

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), fail_tool, mutating=True))

    plan = ExecutionPlan.create(
        goal="Modificar y crear entidades",
        tasks=[
            {"id": "t1", "objective": "Renombrar Factura", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Agregar Detalle a Factura", "kind": "mutation", "depends_on": ["t1"]},
            {"id": "t3", "objective": "Crear Cliente independiente", "kind": "mutation", "depends_on": ["t1"]},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert result.metadata is not None
    assert result.metadata["kind"] == "terminal_domain_failure"
    assert result.metadata["category"] == DomainFailureCategory.CLASS_NOT_FOUND.value
    assert result.metadata["error_code"] == "class_not_found"
    assert result.metadata["task_id"] == "t1"
    assert result.metadata["has_confirmed_changes"] is False

    # Mensaje determinista en español, sin UUIDs ni razonamiento técnico
    assert "no está disponible en el diagrama" in result.text
    assert "Factura" in result.text
    assert "revisar el diagrama antes de volver a intentarlo" in result.text

    # Estado de las tareas en el plan
    t1 = plan.get_task("t1")
    t2 = plan.get_task("t2")
    t3 = plan.get_task("t3")
    assert t1["status"] == "failed"
    assert t1["error_code"] == "class_not_found"
    assert t2["status"] == "blocked"
    assert t3["status"] == "blocked"

    # Verificación de corte estricto: CERO inferencias adicionales (ni síntesis ni resumen)
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_terminal_attribute_not_found_preserves_confirmed_prior_commits():
    # T007: Atributo ausente tras cambios previos confirmados conserva commits en el ledger
    # y los refleja en el mensaje predeterminado.
    t1_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Usuario"}]},
    )
    t2_call = AiToolCall(
        id="c2",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "UPDATE_ATTRIBUTE", "name": "email"}]},
    )
    provider = SequenceProvider([
        AiResult(
            text="Creando clase",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(t1_call,),
        ),
        AiResult(
            text="Clase creada con éxito.",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
        AiResult(
            text="Modificando atributo",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(t2_call,),
        ),
    ])

    registry = ToolRegistry()

    async def mutate_or_fail(arguments, report=None):
        actions = arguments.get("actions", [])
        if actions and actions[0].get("kind") == "CREATE_CLASS":
            if report is not None:
                await report({
                    "operation_id": "op-1",
                    "status": "applied",
                    "entity_refs": [{"id": "cls-1", "type": "class", "name": "Usuario"}],
                })
            return {"status": "applied", "mutation_applied": True}
        raise DiagramAttributeNotFoundException()

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mutate_or_fail, mutating=True))

    plan = ExecutionPlan.create(
        goal="Crear usuario y configurar atributo",
        tasks=[
            {"id": "t1", "objective": "Crear Usuario", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Actualizar email", "kind": "mutation", "depends_on": ["t1"]},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert result.metadata["kind"] in {"terminal_domain_failure", "continuation"}
    assert result.metadata["category"] == DomainFailureCategory.ATTRIBUTE_NOT_FOUND.value
    assert result.metadata["has_confirmed_changes"] is True

    # Mensaje predefinido reconoce que los cambios anteriores se conservan
    assert "Usuario" in result.text
    assert "email" in result.text
    assert "1 tarea" in result.text
    assert "1 pendiente" in result.text

    # Tarea 1 completada, tarea 2 fallida
    assert plan.get_task("t1")["status"] == "completed"
    assert plan.get_task("t2")["status"] == "failed"
    assert plan.get_task("t2")["error_code"] == "attribute_not_found"

    # Cero inferencias tras el fallo (2 para t1, 1 para t2, 0 síntesis/resumen)
    assert len(provider.requests) == 3


@pytest.mark.anyio
async def test_terminal_relation_not_found_in_batch_skips_remaining_tool_calls():
    # T007: En un lote de tool calls en la misma respuesta del modelo,
    # el primer fallo terminal interrumpe de inmediato las llamadas posteriores.
    executed_tools = []

    c1 = AiToolCall(id="c1", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "A"}]})
    c2 = AiToolCall(id="c2", name="apply_diagram_changes", arguments={"actions": [{"kind": "DELETE_RELATION", "name": "rel_ab"}]})
    c3 = AiToolCall(id="c3", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "B"}]})

    provider = SequenceProvider([
        AiResult(
            text="Ejecutando lote",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(c1, c2, c3),
        ),
    ])

    registry = ToolRegistry()

    async def batch_handler(arguments, report=None):
        actions = arguments.get("actions", [])
        kind = actions[0].get("kind") if actions else "unknown"
        executed_tools.append(kind)
        if kind == "CREATE_CLASS":
            if report is not None:
                await report({
                    "operation_id": "op-1",
                    "status": "applied",
                    "entity_refs": [{"id": "cls-a", "type": "class", "name": "A"}],
                })
            return {"status": "applied", "mutation_applied": True}
        if kind == "DELETE_RELATION":
            raise DiagramRelationNotFoundException()
        return {"status": "applied", "mutation_applied": True}

    registry.register(RegisteredTool(_tool("apply_diagram_changes"), batch_handler, mutating=True))

    plan = ExecutionPlan.create(
        goal="Lote de modificaciones",
        tasks=[{"id": "t1", "objective": "Ejecutar lote", "kind": "mutation"}],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert result.metadata["kind"] == "terminal_domain_failure"
    assert result.metadata["category"] == DomainFailureCategory.RELATION_NOT_FOUND.value
    assert result.metadata["has_confirmed_changes"] is True

    # El tercer tool call (c3) NUNCA se ejecutó
    assert executed_tools == ["CREATE_CLASS", "DELETE_RELATION"]
    assert "rel_ab" in result.text


@pytest.mark.anyio
async def test_zero_inferences_and_tool_calls_after_terminal_failure_in_batch():
    # T013: Verificar con contadores que tras un fallo terminal en un lote de llamadas,
    # hay exactamente 0 llamadas a herramientas posteriores y 0 inferencias adicionales.
    c1 = AiToolCall(id="c1", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "EntidadA"}]})
    c2 = AiToolCall(id="c2", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "EntidadA"}]})
    c3 = AiToolCall(id="c3", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "EntidadB"}]})
    c4 = AiToolCall(id="c4", name="apply_diagram_changes", arguments={"actions": [{"kind": "CREATE_CLASS", "name": "EntidadC"}]})

    provider = CountingAiProvider(
        responses=[
            AiResult(
                text="Creando varias entidades",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(c1, c2, c3, c4),
            )
        ]
    )

    base_registry = ToolRegistry()
    executed_ops = []

    async def counting_mutate(arguments, report=None):
        actions = arguments.get("actions", [])
        kind = actions[0].get("kind") if actions else "unknown"
        executed_ops.append(actions[0].get("name"))
        if len(executed_ops) == 1:
            if report is not None:
                await report({
                    "operation_id": "op-1",
                    "status": "applied",
                    "entity_refs": [{"id": "cls-1", "type": "class", "name": "EntidadA"}],
                })
            return {"status": "applied", "mutation_applied": True}
        # Segunda llamada lanza conflicto de nombre existente
        raise DiagramClassNameAlreadyExistsException()

    base_registry.register(RegisteredTool(_tool("apply_diagram_changes"), counting_mutate, mutating=True))
    counting_registry = CountingToolRegistry(real_registry=base_registry)

    plan = ExecutionPlan.create(
        goal="Crear catálogo completo",
        tasks=[{"id": "task-catalog", "objective": "Crear entidades en lote", "kind": "mutation"}],
    )

    result = await PlanExecutor(provider, counting_registry).execute(_context(), plan)

    assert result.completed is False
    assert result.metadata["kind"] == "terminal_domain_failure"
    assert result.metadata["category"] == DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE.value
    assert result.metadata["error_code"] == "class_name_conflict"

    # Garantía estricta: exactamente 1 inferencia enviada al proveedor (0 síntesis, 0 reintentos)
    assert provider.complete_calls_count == 1

    # Exactamente 2 tool calls ejecutados en el registry (c1 exitoso, c2 falló; c3 y c4 NUNCA se tocaron)
    assert counting_registry.tool_calls_count == 2
    assert executed_ops == ["EntidadA", "EntidadA"]


@pytest.mark.anyio
async def test_zero_inferences_on_independent_tasks_after_terminal_failure():
    # T013 / T015: Plan con múltiples tareas sin dependencias entre sí.
    # El primer fallo terminal debe cancelar/bloquear las tareas restantes sin llamar al modelo.
    t1_call = AiToolCall(id="t1-c1", name="apply_diagram_changes", arguments={"actions": [{"kind": "DELETE_ATTRIBUTE", "attr": "id"}]})

    provider = CountingAiProvider(
        responses=[
            AiResult(
                text="Iniciando tarea 1",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(t1_call,),
            ),
            # Si el ejecutor intentara ejecutar t2 o t3, consumiría estas respuestas
            AiResult(text="Respuesta espuria t2", model_role=ModelRole.MAIN, model="qwen"),
            AiResult(text="Respuesta espuria t3", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )

    base_registry = ToolRegistry()

    async def mutate_pk_fail(_arguments, _report=None):
        raise PrimaryKeyCannotBeDeletedException()

    base_registry.register(RegisteredTool(_tool("apply_diagram_changes"), mutate_pk_fail, mutating=True))
    counting_registry = CountingToolRegistry(real_registry=base_registry)

    plan = ExecutionPlan.create(
        goal="Eliminar y crear cosas en paralelo",
        tasks=[
            {"id": "t1", "objective": "Eliminar llave primaria", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Crear otra entidad", "kind": "mutation", "depends_on": ["t1"]},
            {"id": "t3", "objective": "Consultar relaciones", "kind": "answer", "depends_on": ["t1"]},
        ],
    )

    result = await PlanExecutor(provider, counting_registry).execute(_context(), plan)

    assert result.completed is False
    assert result.metadata["kind"] == "terminal_domain_failure"
    assert result.metadata["category"] == DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE.value
    assert result.metadata["error_code"] == "primary_key_cannot_be_deleted"

    # Tarea 1 fallida, tareas 2 y 3 bloqueadas antes de iniciar
    assert plan.get_task("t1")["status"] == "failed"
    assert plan.get_task("t2")["status"] == "blocked"
    assert plan.get_task("t3")["status"] == "blocked"

    # Exactamente 1 inferencia y 1 tool call realizados en total
    assert provider.complete_calls_count == 1
    assert counting_registry.tool_calls_count == 1


@pytest.mark.anyio
async def test_domain_failure_continues_independent_tasks_yielding_partial_plan():
    # T007 [US1]: Un conflicto de dominio en una tarea bloquea sus descendientes pero
    # permite que las tareas independientes continúen su ejecución, arrojando resultado partial.
    t1_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "RENAME_CLASS", "name": "Factura"}]},
    )
    t3_call = AiToolCall(
        id="c3",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Cliente"}]},
    )

    provider = SequenceProvider([
        # Ejecución de t1
        AiResult(
            text="Renombrando Factura",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(t1_call,),
        ),
        # Ejecución de t3 (independiente)
        AiResult(
            text="Creando Cliente",
            model_role=ModelRole.MAIN,
            model="qwen",
            tool_calls=(t3_call,),
        ),
        AiResult(
            text="Cliente creado exitosamente",
            model_role=ModelRole.MAIN,
            model="qwen",
        ),
    ])

    executed_tools = []

    async def mock_tool(arguments, _report=None):
        actions = arguments.get("actions", [])
        kind = actions[0].get("kind") if actions else ""
        executed_tools.append(kind)
        if kind == "RENAME_CLASS":
            raise DiagramClassNotFoundException()
        return {
            "status": "applied",
            "operation_id": "op-cliente",
            "entity_refs": [{"type": "class", "id": "id-cliente", "name": "Cliente"}],
        }

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_tool, mutating=True))

    plan = ExecutionPlan.create(
        goal="Modificar y crear entidades independientes",
        tasks=[
            {"id": "t1", "objective": "Renombrar Factura", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Agregar Detalle a Factura", "kind": "mutation", "depends_on": ["t1"]},
            {"id": "t3", "objective": "Crear Cliente independiente", "kind": "mutation", "depends_on": []},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    # 1. El resultado global es no completado / partial
    assert result.completed is False
    assert result.metadata is not None
    assert result.metadata.get("outcome") == "partial" or plan.status == "partial"

    # 2. t1 falló, t2 (descendiente) fue bloqueada, t3 (independiente) se completó
    assert plan.get_task("t1")["status"] == "failed"
    assert plan.get_task("t1")["error_code"] == "class_not_found"
    assert plan.get_task("t2")["status"] == "blocked"
    assert plan.get_task("t2")["error_code"] == "blocked_by_t1"
    assert plan.get_task("t3")["status"] == "completed"

    # 3. Estado general del plan es partial
    assert plan.status == "partial"

    # 4. Ambas herramientas invocadas
    assert executed_tools == ["RENAME_CLASS", "CREATE_CLASS"]

    # 5. Cero inferencias adicionales para explicar errores de dominio
    assert len(provider.requests) == 3


@pytest.mark.anyio
async def test_domain_failures_across_multiple_tasks_captures_reasons_and_no_ai_synthesis():
    # T007 [US1]: Múltiples tareas independientes con conflictos de dominio
    # capturan sus motivos de fallo seguros sin invocar al modelo para sintetizar explicaciones.
    t1_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "RENAME_CLASS", "name": "Factura"}]},
    )
    t2_call = AiToolCall(
        id="c2",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "DELETE_ATTRIBUTE", "attr": "codigo"}]},
    )

    provider = SequenceProvider([
        AiResult(text="Paso 1", model_role=ModelRole.MAIN, model="qwen", tool_calls=(t1_call,)),
        AiResult(text="Paso 2", model_role=ModelRole.MAIN, model="qwen", tool_calls=(t2_call,)),
    ])

    async def mock_tool(arguments, _report=None):
        actions = arguments.get("actions", [])
        kind = actions[0].get("kind") if actions else ""
        if kind == "RENAME_CLASS":
            raise DiagramClassNotFoundException()
        raise DiagramAttributeNotFoundException()

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mock_tool, mutating=True))

    plan = ExecutionPlan.create(
        goal="Dos tareas con fallo de dominio",
        tasks=[
            {"id": "t1", "objective": "Renombrar Factura", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Borrar codigo", "kind": "mutation", "depends_on": []},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert plan.get_task("t1")["status"] == "failed"
    assert plan.get_task("t1")["error_code"] == "class_not_found"
    assert plan.get_task("t2")["status"] == "failed"
    assert plan.get_task("t2")["error_code"] == "attribute_not_found"
    assert plan.status == "failed"
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_global_stop_preserved_for_uncertain_operations():
    # T007 [US1]: Una operación en estado 'uncertain' detiene inmediatamente la ejecución
    # de todo el plan para evitar inconsistencias en el diagrama.
    t1_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Pedido"}]},
    )
    t2_call = AiToolCall(
        id="c2",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "CREATE_CLASS", "name": "Producto"}]},
    )

    provider = SequenceProvider([
        AiResult(text="Paso 1", model_role=ModelRole.MAIN, model="qwen", tool_calls=(t1_call,)),
        AiResult(text="Paso 2", model_role=ModelRole.MAIN, model="qwen", tool_calls=(t2_call,)),
    ])

    async def uncertain_tool(_arguments, _report=None):
        return {
            "status": "uncertain",
            "operation_id": "op-incierta",
            "entity_refs": [],
        }

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), uncertain_tool, mutating=True))

    plan = ExecutionPlan.create(
        goal="Detención global por uncertain",
        tasks=[
            {"id": "t1", "objective": "Crear Pedido", "kind": "mutation", "depends_on": []},
            {"id": "t2", "objective": "Crear Producto", "kind": "mutation", "depends_on": []},
        ],
    )

    result = await PlanExecutor(provider, registry).execute(_context(), plan)

    assert result.completed is False
    assert plan.status == "uncertain"
    # t2 jamás se ejecutó porque uncertain detiene globalmente
    assert plan.get_task("t2")["status"] == "pending"
    assert len(provider.requests) == 2


@pytest.mark.anyio
async def test_plan_executor_read_only_authorized_mode_forbids_mutations_even_with_mutation_verbs():
    # T017 [US3]: Una consulta con authorized_mode="read_only" no habilita herramientas de mutación
    # aunque el prompt del usuario contenga verbos de mutación ("crea", "elimina").
    overview_call = AiToolCall(
        id="c-overview",
        name="get_diagram_overview",
        arguments={},
    )
    provider = SequenceProvider([
        AiResult(text="Consultando estado.", model_role=ModelRole.MAIN, model="qwen", tool_calls=(overview_call,)),
        AiResult(text="El diagrama contiene las clases actuales.", model_role=ModelRole.MAIN, model="qwen"),
    ])

    mutation_executed = False

    async def mutate_tool(_arguments, _report=None):
        nonlocal mutation_executed
        mutation_executed = True
        return {"status": "applied"}

    async def overview_tool(_arguments, _report=None):
        return {"status": "success", "classes": ["Producto"]}

    registry = ToolRegistry()
    registry.register(RegisteredTool(_tool("apply_diagram_changes"), mutate_tool, mutating=True))
    registry.register(RegisteredTool(_tool("get_diagram_overview"), overview_tool, mutating=False))

    ctx = replace(
        _context(prompt="crea una clase llamada Factura y elimina Producto"),
        authorized_mode="read_only",
    )

    plan = ExecutionPlan.create(
        goal="crea una clase llamada Factura y elimina Producto",
        tasks=[
            {"id": "t1", "objective": "crea Factura y elimina Producto", "kind": "mutation", "depends_on": []},
        ],
    )

    executor = PlanExecutor(provider, registry)
    result = await executor.execute(ctx, plan)

    # 1. Las herramientas ofrecidas al modelo jamás deben incluir apply_diagram_changes
    first_request = provider.requests[0]
    offered_tool_names = [t.name for t in first_request.tools]
    assert "apply_diagram_changes" not in offered_tool_names
    assert "get_diagram_overview" in offered_tool_names

    # 2. La herramienta de mutación jamás fue ejecutada
    assert mutation_executed is False

    # 3. No se registraron cambios aplicados en el ledger
    assert not any(entry.get("status") == "applied" for entry in plan.operation_ledger)









