import pytest

from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import (
    AgentToolArgumentsException,
    AgentToolLimitException,
    UnknownAgentToolException,
)


def _definition(name="read_project"):
    return AiToolDefinition(
        name=name,
        description="Lee un recurso del proyecto.",
        parameters={"type": "object", "additionalProperties": False},
    )


@pytest.mark.anyio
async def test_registry_executes_only_registered_handler():
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            _definition(),
            lambda arguments, _progress: {"query": arguments["query"]},
        )
    )

    result = await registry.execute("read_project", {"query": "Producto"})

    assert result == {"query": "Producto"}
    assert [tool.name for tool in registry.definitions] == ["read_project"]


@pytest.mark.anyio
async def test_registry_rejects_unknown_tools_non_objects_and_oversized_arguments():
    registry = ToolRegistry(max_arguments_chars=12)
    registry.register(RegisteredTool(_definition(), lambda _args, _progress: {}))

    with pytest.raises(UnknownAgentToolException):
        await registry.execute("delete_everything", {})
    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("read_project", ["not", "an", "object"])
    with pytest.raises(AgentToolLimitException):
        await registry.execute("read_project", {"query": "a long request"})


@pytest.mark.anyio
async def test_answer_only_task_does_not_expose_or_execute_mutations():
    registry = ToolRegistry()
    registry.register(RegisteredTool(_definition("read_project"), lambda _args, _progress: {}))
    registry.register(RegisteredTool(_definition("mutate_project"), lambda _args, _progress: {}, mutating=True))

    assert [tool.name for tool in registry.definitions_for_task(mutation_allowed=False)] == [
        "read_project"
    ]
    with pytest.raises(UnknownAgentToolException):
        await registry.execute(
            "mutate_project",
            {},
            allowed_names=registry.allowed_names_for_task(mutation_allowed=False),
        )


@pytest.mark.anyio
async def test_operation_ledger_records_all_valid_statuses_and_preserves_applied_immutability():
    """T025 [US4]: El ledger registra propuesto, validado, aplicado, rechazado e incierto."""
    from app.modules.assistant.application.services.execution.operation_ledger import OperationLedger
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    plan = ExecutionPlan.create(
        goal="Probar estados del ledger",
        tasks=[{"id": "task-1", "objective": "Objetivo", "kind": "mutation"}],
    )

    # 1. Propuesto
    OperationLedger.record(
        plan,
        operation_id="op-1",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-1",
        event={"status": "proposed", "action_kind": "CREATE_CLASS"},
    )
    assert len(plan.operation_ledger) == 1
    assert plan.operation_ledger[0]["status"] == "proposed"
    assert plan.operation_ledger[0]["action_kind"] == "CREATE_CLASS"

    # 2. Validado
    OperationLedger.record(
        plan,
        operation_id="op-1",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-1",
        event={"status": "validated"},
    )
    assert plan.operation_ledger[0]["status"] == "validated"

    # 3. Aplicado (con entity_refs normalizados y committed_at)
    OperationLedger.record(
        plan,
        operation_id="op-1",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-1",
        event={
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "cls-uuid-1"}],
            "derived_effects": [{"type": "auto_pk", "name": "id"}],
        },
    )
    assert plan.operation_ledger[0]["status"] == "applied"
    assert plan.operation_ledger[0]["entity_refs"] == [{"type": "class", "id": "cls-uuid-1"}]
    assert "committed_at" in plan.operation_ledger[0]

    # Regla de integridad: No se puede degradar un estado 'applied'
    OperationLedger.record(
        plan,
        operation_id="op-1",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-1",
        event={"status": "rejected", "error_code": "should_be_ignored"},
    )
    assert plan.operation_ledger[0]["status"] == "applied"

    # 4. Rechazado
    OperationLedger.record(
        plan,
        operation_id="op-2",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-2",
        event={"status": "rejected", "error_code": "invalid_arguments", "action_kind": "CREATE_ATTRIBUTE"},
    )
    op_2 = next(op for op in plan.operation_ledger if op["operation_id"] == "op-2")
    assert op_2["status"] == "rejected"
    assert op_2["error_code"] == "invalid_arguments"

    # 5. Incierto
    OperationLedger.record(
        plan,
        operation_id="op-3",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        input_digest="digest-3",
        event={"status": "uncertain", "error_code": "uncertain_result", "action_kind": "CREATE_RELATION"},
    )
    op_3 = next(op for op in plan.operation_ledger if op["operation_id"] == "op-3")
    assert op_3["status"] == "uncertain"
    assert op_3["error_code"] == "uncertain_result"

    # Verificación de helpers
    assert OperationLedger.has_uncertain_operations(plan) is True
    assert OperationLedger.has_applied_operations(plan) is True
    applied = OperationLedger.get_operations_by_status(plan, "applied")
    assert len(applied) == 1
    assert applied[0]["operation_id"] == "op-1"

    # 6. Rechazo de estado inválido
    with pytest.raises(ValueError, match="Estado de operación inválido"):
        OperationLedger.record(
            plan,
            operation_id="op-invalid",
            task_id="task-1",
            tool_name="apply_diagram_changes",
            input_digest="digest-x",
            event={"status": "invented_status"},
        )


@pytest.mark.anyio
async def test_tool_registry_progress_reporter_integration_with_ledger():
    """T025 [US4]: ToolRegistry integra con reporter y actualiza el ledger del plan."""
    from app.modules.assistant.application.services.execution.operation_ledger import OperationLedger
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    plan = ExecutionPlan.create(
        goal="Ejecución con registry y reporter",
        tasks=[{"id": "t1", "objective": "Mutar", "kind": "mutation"}],
    )

    async def custom_mutator(arguments, report):
        if report is not None:
            await report({"operation_id": "op-reg-1", "action_kind": "CREATE_CLASS", "status": "proposed"})
            await report({"operation_id": "op-reg-1", "action_kind": "CREATE_CLASS", "status": "validated"})
            await report({
                "operation_id": "op-reg-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "cls-new-id"}],
            })
        return {"status": "applied", "results": [{"operation_id": "op-reg-1", "status": "applied"}]}

    registry = ToolRegistry()
    registry.register(RegisteredTool(_definition("apply_diagram_changes"), custom_mutator, mutating=True))

    async def reporter(event):
        OperationLedger.record(
            plan,
            operation_id=event["operation_id"],
            task_id="t1",
            tool_name="apply_diagram_changes",
            input_digest="hash123",
            event=event,
        )

    result = await registry.execute("apply_diagram_changes", {"actions": []}, progress=reporter)
    assert result["status"] == "applied"
    assert len(plan.operation_ledger) == 1
    assert plan.operation_ledger[0]["status"] == "applied"
    assert plan.operation_ledger[0]["entity_refs"] == [{"type": "class", "id": "cls-new-id"}]

