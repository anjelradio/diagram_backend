"""Pruebas de reconciliación de operaciones inciertas antes de continuar (US2)."""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.application.services.continuation.residual_plan_builder import (
    ResidualPlanBuilder,
    UnreconciledOperationException,
    reconcile_uncertain_operation,
)


def _make_uncertain_plan() -> tuple[ExecutionPlan, str, str]:
    t1_id = str(uuid4())
    op_id = "op-uncertain-1"
    tasks = [
        {
            "id": t1_id,
            "objective": "Crear clase Factura",
            "status": "uncertain",
            "depends_on": [],
            "operation_ids": [op_id],
        }
    ]
    ledger = [
        {
            "operation_id": op_id,
            "task_id": t1_id,
            "tool_name": "diagram_class_tools",
            "action_kind": "CREATE_CLASS",
            "status": "uncertain",
            "entity_refs": [{"id": "factura-1", "type": "class", "name": "Factura"}],
        }
    ]
    plan = ExecutionPlan.create(goal="Crear clase Factura", tasks=tasks)
    plan.operation_ledger = ledger
    return plan, t1_id, op_id


def test_residual_plan_blocks_unreconciled_uncertain_operations():
    """Un plan con operaciones en estado 'uncertain' debe ser bloqueado si no han sido reconciliadas."""
    plan, _, _ = _make_uncertain_plan()
    builder = ResidualPlanBuilder()

    with pytest.raises(UnreconciledOperationException) as exc_info:
        builder.build(plan)

    assert "incierto" in str(exc_info.value).lower() or "uncertain" in str(exc_info.value).lower()


def test_residual_plan_allows_resumption_when_reconciled_as_applied():
    """Si la reconciliación confirma que la operación incierta sí se aplicó en el diagrama, se marca applied y no se repite."""
    plan, t1_id, op_id = _make_uncertain_plan()
    builder = ResidualPlanBuilder()

    # Reconciliador que confirma que la clase sí existe en el diagrama
    def mock_reconciler(entry: dict) -> bool | None:
        if entry.get("operation_id") == op_id:
            return True  # Confirmado que sí se aplicó
        return None

    residual = builder.build(plan, reconciler=mock_reconciler)

    # Como la única tarea era t1 y se confirmó aplicada, no queda trabajo pendiente
    assert residual is None
    # En el ledger del plan, la operación debe haber pasado a 'applied'
    op_entry = next(e for e in plan.operation_ledger if e["operation_id"] == op_id)
    assert op_entry["status"] == "applied"


def test_residual_plan_allows_resumption_when_reconciled_as_rejected():
    """Si la reconciliación confirma que la operación incierta no se aplicó en el diagrama, se marca rejected y se puede reintentar."""
    plan, t1_id, op_id = _make_uncertain_plan()
    builder = ResidualPlanBuilder()

    # Reconciliador que confirma que la clase no existe en el diagrama
    def mock_reconciler(entry: dict) -> bool | None:
        if entry.get("operation_id") == op_id:
            return False  # Confirmado que no se aplicó
        return None

    residual = builder.build(plan, reconciler=mock_reconciler)

    # La tarea debe reintentarse en el plan residual
    assert residual is not None
    assert len(residual.tasks) == 1
    assert residual.tasks[0]["id"] == t1_id
    assert residual.tasks[0]["status"] == "pending"


def test_reconcile_uncertain_operation_with_diagram_reader():
    """La función de utilidad reconcile_uncertain_operation consulta el estado real de la entidad."""
    class FakeDiagramReader:
        def __init__(self, existing_names: set[str]):
            self.existing_names = existing_names

        def get_class_by_name(self, name: str) -> dict | None:
            if name in self.existing_names:
                return {"id": "cls-1", "name": name}
            return None

    reader = FakeDiagramReader(existing_names={"Factura"})

    entry_applied = {
        "operation_id": "op-1",
        "action_kind": "CREATE_CLASS",
        "entity_refs": [{"name": "Factura", "type": "class"}],
    }
    assert reconcile_uncertain_operation(entry_applied, diagram_reader=reader) is True

    entry_not_applied = {
        "operation_id": "op-2",
        "action_kind": "CREATE_CLASS",
        "entity_refs": [{"name": "Producto", "type": "class"}],
    }
    assert reconcile_uncertain_operation(entry_not_applied, diagram_reader=reader) is False
