"""Pruebas del constructor de planes residuales para ejecuciones parciales (US2)."""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.application.services.continuation.residual_plan_builder import (
    ResidualPlanBuilder,
    UnreconciledOperationException,
)


def _make_plan(
    tasks: list[dict],
    ledger: list[dict] | None = None,
    goal: str = "Crear modelo de datos",
) -> ExecutionPlan:
    plan = ExecutionPlan.create(goal=goal, tasks=tasks)
    if ledger:
        plan.operation_ledger = ledger
    return plan


def test_residual_plan_excludes_completed_tasks_and_applied_operations():
    """Las tareas completadas y operaciones aplicadas no deben figurar en el plan residual."""
    t1_id = str(uuid4())
    t2_id = str(uuid4())
    tasks = [
        {
            "id": t1_id,
            "objective": "Crear clase Factura",
            "kind": "mutation",
            "status": "completed",
            "depends_on": [],
            "operation_ids": ["op-1"],
            "result_refs": [{"id": "factura-id", "type": "class"}],
        },
        {
            "id": t2_id,
            "objective": "Crear atributo total en Factura",
            "kind": "mutation",
            "status": "pending",
            "depends_on": [t1_id],
            "operation_ids": ["op-2"],
            "result_refs": [],
        },
    ]
    ledger = [
        {
            "operation_id": "op-1",
            "task_id": t1_id,
            "tool_name": "diagram_class_tools",
            "action_kind": "CREATE_CLASS",
            "status": "applied",
            "entity_refs": [{"id": "factura-id", "type": "class", "name": "Factura"}],
        }
    ]
    plan = _make_plan(tasks, ledger)

    builder = ResidualPlanBuilder()
    residual = builder.build(plan, new_goal="Continuar con atributo total")

    assert residual is not None
    assert len(residual.tasks) == 1
    remaining_task = residual.tasks[0]
    assert remaining_task["id"] == t2_id
    assert remaining_task["objective"] == "Crear atributo total en Factura"
    assert remaining_task["status"] == "pending"


def test_residual_plan_satisfies_dependencies_for_applied_tasks():
    """Las dependencias de tareas hacia tareas ya aplicadas deben considerarse satisfechas (removidas de depends_on)."""
    t1_id = str(uuid4())
    t2_id = str(uuid4())
    t3_id = str(uuid4())
    tasks = [
        {
            "id": t1_id,
            "objective": "Crear clase Usuario",
            "status": "completed",
            "depends_on": [],
        },
        {
            "id": t2_id,
            "objective": "Crear clase Rol",
            "status": "failed",
            "depends_on": [t1_id],
        },
        {
            "id": t3_id,
            "objective": "Asociar Usuario con Rol",
            "status": "blocked",
            "depends_on": [t1_id, t2_id],
        },
    ]
    ledger = [
        {
            "operation_id": "op-u",
            "task_id": t1_id,
            "status": "applied",
            "entity_refs": [{"id": "user-id", "type": "class", "name": "Usuario"}],
        }
    ]
    plan = _make_plan(tasks, ledger)

    builder = ResidualPlanBuilder()
    residual = builder.build(plan)

    assert residual is not None
    assert len(residual.tasks) == 2

    res_t2 = next(t for t in residual.tasks if t["id"] == t2_id)
    assert res_t2["status"] == "pending"
    # t1 ya se aplicó, por tanto la dependencia hacia t1 queda satisfecha
    assert res_t2["depends_on"] == []

    res_t3 = next(t for t in residual.tasks if t["id"] == t3_id)
    assert res_t3["status"] == "pending"
    # t1 satisfecha, pero t2 aún está en el plan residual, luego depends_on conserva t2
    assert res_t3["depends_on"] == [t2_id]


def test_residual_plan_preserves_confirmed_entity_refs():
    """El plan residual debe conservar las referencias confirmadas para que las herramientas resuelvan IDs previos."""
    t1_id = str(uuid4())
    t2_id = str(uuid4())
    tasks = [
        {"id": t1_id, "objective": "Crear clase Factura", "status": "completed", "depends_on": []},
        {"id": t2_id, "objective": "Crear atributo", "status": "pending", "depends_on": [t1_id]},
    ]
    ledger = [
        {
            "operation_id": "op-1",
            "task_id": t1_id,
            "tool_name": "diagram_class_tools",
            "status": "applied",
            "entity_refs": [{"id": "factura-123", "type": "class", "name": "Factura"}],
        }
    ]
    plan = _make_plan(tasks, ledger)

    builder = ResidualPlanBuilder()
    residual = builder.build(plan)

    assert residual is not None
    confirmed_refs = residual.get_confirmed_entity_refs()
    assert len(confirmed_refs) == 1
    assert confirmed_refs[0]["id"] == "factura-123"
    assert confirmed_refs[0]["name"] == "Factura"


def test_residual_plan_handles_partially_applied_task():
    """Una tarea con operaciones ya aplicadas debe conservar solo las pendientes sin duplicar las aplicadas."""
    t1_id = str(uuid4())
    tasks = [
        {
            "id": t1_id,
            "objective": "Crear clase Cliente y atributo email",
            "status": "failed",
            "depends_on": [],
            "operation_ids": ["op-c", "op-e"],
        }
    ]
    ledger = [
        {
            "operation_id": "op-c",
            "task_id": t1_id,
            "status": "applied",
            "entity_refs": [{"id": "cli-1", "type": "class", "name": "Cliente"}],
        },
        {
            "operation_id": "op-e",
            "task_id": t1_id,
            "status": "rejected",
            "entity_refs": [],
        },
    ]
    plan = _make_plan(tasks, ledger)

    builder = ResidualPlanBuilder()
    residual = builder.build(plan)

    assert residual is not None
    assert len(residual.tasks) == 1
    task = residual.tasks[0]
    assert task["id"] == t1_id
    assert task["status"] == "pending"
    # op-c ya fue aplicada, solo queda op-e
    assert "op-c" not in task.get("operation_ids", [])


def test_residual_plan_returns_none_when_all_tasks_completed():
    """Si todas las tareas ya están completadas y aplicadas, no se genera plan residual."""
    t1_id = str(uuid4())
    tasks = [
        {"id": t1_id, "objective": "Crear clase", "status": "completed", "depends_on": []}
    ]
    ledger = [{"operation_id": "op-1", "task_id": t1_id, "status": "applied", "entity_refs": []}]
    plan = _make_plan(tasks, ledger)

    builder = ResidualPlanBuilder()
    residual = builder.build(plan)

    assert residual is None


def test_residual_plan_schedules_new_instruction_without_repeating_completed_work():
    prior = _make_plan([
        {"id": "created", "objective": "Crea Venta", "status": "completed"},
        {"id": "pending", "objective": "Agrega total a Venta", "status": "failed"},
        {"id": "report", "objective": "Consulta Venta", "kind": "answer", "depends_on": ["pending"]},
    ])

    residual = ResidualPlanBuilder().build(prior, additional_request="Agrega estado a Venta")

    assert residual is not None
    tasks = {task["id"]: task for task in residual.tasks}
    assert set(tasks) == {"pending", "report", "additional-request"}
    assert tasks["additional-request"]["objective"] == "Agrega estado a Venta"
    assert tasks["additional-request"]["depends_on"] == ["pending"]
    assert tasks["report"]["depends_on"] == ["pending", "additional-request"]
