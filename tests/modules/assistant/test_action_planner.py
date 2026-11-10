import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.planning.action_planner import ActionPlanner
from app.modules.assistant.domain.exceptions import (
    ExecutionPlanErrorReason,
    InvalidExecutionPlanException,
)


class PlannerProvider:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return AiResult(
            text=self.text,
            model_role=request.model_role,
            model="test-model",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "max_tasks", "reason"),
    [
        ('not valid json', 4, ExecutionPlanErrorReason.PLANNER_INVALID_JSON),
        ('[]', 4, ExecutionPlanErrorReason.PLANNER_NOT_OBJECT),
        ('{"goal":"test","tasks":[]}', 4, ExecutionPlanErrorReason.PLANNER_INVALID_TASKS),
        ('{"goal":"test","tasks":[{},{}]}', 1, ExecutionPlanErrorReason.PLANNER_TASK_LIMIT),
        ('{"goal":"test","tasks":[{"id":"a","objective":"A","depends_on":["missing"]}]}', 4,
         ExecutionPlanErrorReason.PLAN_INVALID_DEPENDENCY),
        ('{"goal":"test","tasks":[{"id":"a","objective":"A"},{"id":"a","objective":"B"}]}', 4,
         ExecutionPlanErrorReason.PLAN_DUPLICATE_TASK_ID),
    ],
)
async def test_planner_reports_safe_validation_reason(response, max_tasks, reason):
    with pytest.raises(InvalidExecutionPlanException) as failure:
        await ActionPlanner(PlannerProvider(response), max_tasks=max_tasks).create_plan(
            "Crea A y edita B"
        )

    assert failure.value.reason is reason
    assert response not in str(failure.value)


def test_single_intent_uses_direct_route_and_compound_or_mixed_prompt_plans():
    assert not ActionPlanner.requires_plan("Crea la clase Producto")
    assert ActionPlanner.requires_plan("Crea Producto, relaciona Pedido y dime si está bien")
    assert ActionPlanner.requires_plan("Crea Producto y luego agrega precio")


def test_subjunctive_requests_keep_mutation_tools_and_plan_compound_work():
    prompt = (
        "Quiero que crees una clase llamada Caballo con atributos Establo, SESPE y Cerca. "
        "También quiero que crees Pato y luego quiero que relaciones Caballo con Pato "
        "de muchos a muchos."
    )
    assert ActionPlanner.requires_mutation(prompt)
    assert ActionPlanner.requires_plan(prompt)
    assert ActionPlanner.build_direct_plan(prompt).tasks[0]["kind"] == "mutation"
    assert ActionPlanner.requires_mutation("¿Crees que las relaciones están bien?") is False
    assert ActionPlanner.requires_plan("Quiero que crees una clase Caballo") is False


@pytest.mark.parametrize(
    "prompt",
    [
        "es una relación de herencia un gato es animal, la clase padre es Animal y la clase hijo es Cat",
        "Cat hereda de Animal",
        "sería una relación de composición; la clase padre es Casa y la clase hija es Habitación",
    ],
)
def test_relation_configuration_followups_keep_mutation_tools(prompt):
    assert ActionPlanner.requires_mutation(prompt) is True
    assert ActionPlanner.requires_plan(prompt) is False
    assert ActionPlanner.build_direct_plan(prompt).tasks[0]["kind"] == "mutation"


@pytest.mark.parametrize(
    "prompt",
    [
        "¿Es una relación de herencia entre Cat y Animal?",
        "Por ejemplo: Cat hereda de Animal",
        "No relaciones Cat con Animal",
    ],
)
def test_relation_configuration_questions_examples_and_negations_remain_read_only(prompt):
    assert ActionPlanner.requires_mutation(prompt) is False


@pytest.mark.anyio
async def test_planner_creates_valid_task_dag_using_planning_role():
    provider = PlannerProvider(
        '{"goal":"Crear y revisar","tasks":['
        '{"id":"mutate","objective":"Crear entidades","kind":"mutation","depends_on":[]},'
        '{"id":"answer","objective":"Responder sobre el resultado","kind":"answer","depends_on":["mutate"]}]}'
    )
    planner = ActionPlanner(provider, max_tasks=4, max_output_tokens=4_321)

    plan = await planner.create_plan("Crea Producto y dime qué mejorar")

    assert plan is not None
    assert plan.tasks[1]["depends_on"] == ["mutate"]
    assert provider.calls[0].model_role is ModelRole.PLANNING
    assert provider.calls[0].response_format == "text"
    assert provider.calls[0].enable_reasoning is True
    assert provider.calls[0].max_output_tokens == 4_321


@pytest.mark.anyio
async def test_planner_keeps_operation_checklist_for_batched_mutations():
    provider = PlannerProvider(
        '{"goal":"Crear dos clases","tasks":['
        '{"id":"classes","objective":"Crear Producto y Categoria","kind":"mutation",'
        '"depends_on":[],"expected_actions":["CREATE_CLASS","CREATE_CLASS"]}]}'
    )
    plan = await ActionPlanner(provider).create_plan("Crea Producto y luego Categoria")
    assert plan is not None
    assert plan.tasks[0]["expected_actions"] == ["CREATE_CLASS", "CREATE_CLASS"]


@pytest.mark.anyio
async def test_planner_keeps_named_operation_targets():
    provider = PlannerProvider(
        '{"goal":"Crear dos clases","tasks":['
        '{"id":"classes","objective":"Crear Producto y Categoria","kind":"mutation",'
        '"depends_on":[],"expected_actions":['
        '{"kind":"CREATE_CLASS","name":"Producto"},'
        '{"kind":"CREATE_CLASS","name":"Categoria"}]}]}'
    )
    plan = await ActionPlanner(provider).create_plan("Crea Producto y luego Categoria")
    assert plan is not None
    assert plan.tasks[0]["expected_actions"][1]["name"] == "Categoria"


@pytest.mark.anyio
async def test_planner_ignores_malformed_optional_checklist_without_losing_valid_plan():
    provider = PlannerProvider(
        '{"goal":"Crear dos clases","tasks":['
        '{"id":"classes","objective":"Crear Producto y Categoria","kind":"mutation",'
        '"depends_on":[],"expected_actions":[{"kind":"UNKNOWN"}]}]}'
    )
    plan = await ActionPlanner(provider).create_plan("Crea Producto y luego Categoria")
    assert plan is not None
    assert "expected_actions" not in plan.tasks[0]


@pytest.mark.anyio
async def test_planner_normalizes_integer_task_references_from_json():
    provider = PlannerProvider(
        '{"goal":"Crear y relacionar","tasks":['
        '{"id":1,"objective":"Crear entidades","kind":"mutation","depends_on":[]},'
        '{"id":2,"objective":"Relacionar entidades","kind":"mutation","depends_on":[1]}]}'
    )

    plan = await ActionPlanner(provider, max_tasks=4).create_plan(
        "Crea Producto y luego relaciónalo con Pedido"
    )

    assert plan is not None
    assert [task["id"] for task in plan.tasks] == ["1", "2"]
    assert plan.tasks[1]["depends_on"] == ["1"]


@pytest.mark.anyio
async def test_planner_rejects_invalid_or_oversized_plan():
    provider = PlannerProvider('{"goal":"G","tasks":[{"id":"a","objective":"A","depends_on":["b"]}]}')
    with pytest.raises(InvalidExecutionPlanException):
        await ActionPlanner(provider, max_tasks=1).create_plan("Crea A y edita B")


@pytest.mark.anyio
async def test_planner_moves_queries_after_mutations_and_adds_dependencies():
    provider = PlannerProvider(
        '{"goal":"Editar y revisar","tasks":['
        '{"id":"review","objective":"Revisar el resultado","kind":"answer","depends_on":[]},'
        '{"id":"edit","objective":"Editar la clase","kind":"mutation","depends_on":[]}]} '
    )

    plan = await ActionPlanner(provider, max_tasks=4).create_plan(
        "Edita Producto y dime si quedó bien"
    )

    assert [task["id"] for task in plan.tasks] == ["edit", "review"]
    assert plan.tasks[1]["depends_on"] == ["edit"]


@pytest.mark.anyio
async def test_planner_discards_provider_generated_progress_and_unknown_task_fields():
    provider = PlannerProvider(
        '{"goal":"Crear y revisar","tasks":['
        '{"id":"create","objective":"Crear Producto","kind":"mutation",'
        '"depends_on":[],"status":"completed","operation_ids":["fake-op"],'
        '"result_refs":["fake-class"],"error_code":"forged","extra":"ignored"}]}'
    )

    plan = await ActionPlanner(provider, max_tasks=2).create_plan(
        "Crea Producto y después inspecciona el resultado"
    )

    assert plan is not None
    assert plan.tasks == [
        {
            "id": "create",
            "objective": "Crear Producto",
            "kind": "mutation",
            "depends_on": [],
            "status": "pending",
            "operation_ids": [],
            "result_refs": [],
        }
    ]


def test_planner_build_direct_plan_creates_homogeneous_execution_plan():
    """Ruta directa: genera un ExecutionPlan válido con las mismas reglas de validación."""
    mutation_plan = ActionPlanner.build_direct_plan("Crea Producto", max_tool_calls=10)
    assert mutation_plan.goal == "Crea Producto"
    assert len(mutation_plan.tasks) == 1
    assert mutation_plan.tasks[0]["id"] == "direct"
    assert mutation_plan.tasks[0]["kind"] == "mutation"
    assert mutation_plan.tasks[0]["status"] == "pending"
    assert mutation_plan.limits == {"max_tool_calls": 10}

    query_plan = ActionPlanner.build_direct_plan("¿Cuántas clases hay?")
    assert query_plan.tasks[0]["kind"] == "answer"
    assert query_plan.tasks[0]["status"] == "pending"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("prompt", "expected_requires_plan"),
    [
        ("Crea la clase Factura", False),
        ("Crea Factura con id, numero y fecha", False),  # Múltiples atributos de una misma clase: ruta directa
        ("Crea Factura y Crea Detalle", True),  # Múltiples clases / mutaciones compuestas
        ("Crea las clases Producto y Categoria", True),
        ("Agrega atributos precio y stock a Producto", True),
        ("Crea Factura y luego añade fecha", True),  # Marcador de secuencia
        ("Crea Factura y dime si quedó bien", True),  # Mutación + pregunta
        ("¿Qué clases existen en el diagrama?", False),  # Solo lectura
        ("Quiero que crees las clases con sus atributos y también con sus relaciones. Crea absolutamente todo.", True),
        (
            "Crear las clases Producto (con atributos id, nombre, precio, stock), Cliente (con atributos id, nombre, email, teléfono), Venta (con atributos id, fecha, total) y DetalleVenta (con atributos id, cantidad, precio_unitario). Establecer las siguientes relaciones: Asociación 1 a muchos entre Cliente y Venta; Composición 1 a muchos entre Venta y DetalleVenta; y Asociación entre Producto y DetalleVenta.",
            True,
        ),
    ],
)
async def test_planner_requires_plan_distinguishes_direct_and_compound(prompt, expected_requires_plan):
    assert ActionPlanner.requires_plan(prompt) is expected_requires_plan


@pytest.mark.anyio
async def test_planner_rejects_empty_task_objective_and_validates_coverage():
    provider = PlannerProvider('{"goal":"Crear clase","tasks":[{"id":"t1","objective":"   ","kind":"mutation"}]}')
    with pytest.raises(InvalidExecutionPlanException) as exc:
        await ActionPlanner(provider, max_tasks=4).create_plan("Crea Producto y luego crea Pedido")
    assert exc.value.reason in {
        ExecutionPlanErrorReason.PLANNER_INVALID_TASK_FIELDS,
        ExecutionPlanErrorReason.PLAN_INVALID_TASK,
    }


from tests.modules.assistant.fixtures.agent_language_cases import (
    LANGUAGE_TEST_CASES,
    LanguageTestCase,
)


@pytest.mark.parametrize("case", LANGUAGE_TEST_CASES, ids=[c.prompt for c in LANGUAGE_TEST_CASES])
def test_action_planner_corpus_intent_and_mutation(case: LanguageTestCase):
    assert ActionPlanner.requires_mutation(case.prompt) is case.requires_mutation
    direct_plan = ActionPlanner.build_direct_plan(case.prompt)
    expected_kind = "mutation" if case.requires_mutation else "answer"
    assert direct_plan.tasks[0]["kind"] == expected_kind


def test_action_planner_haz_and_crea_equivalence():
    plan_haz = ActionPlanner.build_direct_plan("haz una clase Papanatas con atributo Arcoiris")
    plan_crea = ActionPlanner.build_direct_plan("crea una clase Papanatas con atributo Arcoiris")

    assert plan_haz.tasks[0]["kind"] == "mutation"
    assert plan_crea.tasks[0]["kind"] == "mutation"
    assert ActionPlanner.requires_mutation("haz una clase Papanatas con atributo Arcoiris") is True
    assert ActionPlanner.requires_mutation("crea una clase Papanatas con atributo Arcoiris") is True



