"""Construcción y validación de planes residuales para reanudar ejecuciones parciales."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.modules.assistant.application.services.planning.agent_intent import requires_mutation
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

logger = logging.getLogger(__name__)


class UnreconciledOperationException(Exception):
    """Se lanza cuando una operación incierta no ha sido reconciliada contra el estado real."""
    pass


def reconcile_uncertain_operation(
    entry: dict[str, Any], diagram_reader: Any = None
) -> bool | None:
    """Verifica si el efecto de una operación incierta realmente se aplicó en el diagrama."""
    if diagram_reader is None:
        return None

    action_kind = entry.get("action_kind", "")
    entity_refs = entry.get("entity_refs", [])

    if "CLASS" in action_kind:
        for ref in entity_refs:
            name = ref.get("name")
            if name and hasattr(diagram_reader, "get_class_by_name"):
                found = diagram_reader.get_class_by_name(name)
                return found is not None
            entity_id = ref.get("id")
            if entity_id and hasattr(diagram_reader, "get_class_by_id"):
                found = diagram_reader.get_class_by_id(entity_id)
                return found is not None

    return None


class ResidualPlanBuilder:
    """Construye un nuevo ExecutionPlan residual con únicamente los objetivos y operaciones pendientes."""

    def build(
        self,
        prior_plan: ExecutionPlan | dict[str, Any],
        new_goal: str | None = None,
        reconciler: Callable[[dict[str, Any]], bool | None] | None = None,
        *,
        additional_request: str | None = None,
    ) -> ExecutionPlan | None:
        if isinstance(prior_plan, dict):
            plan = ExecutionPlan.from_dict(prior_plan)
        else:
            plan = prior_plan

        # 1. Reconciliar operaciones inciertas si se suministró un reconciliador
        if reconciler is not None:
            for entry in plan.operation_ledger:
                if entry.get("status") == "uncertain":
                    verdict = reconciler(entry)
                    if verdict is True:
                        entry["status"] = "applied"
                    elif verdict is False:
                        entry["status"] = "rejected"

        # 2. Bloquear si persiste cualquier operación incierta no reconciliada
        for entry in plan.operation_ledger:
            if entry.get("status") == "uncertain":
                op_id = entry.get("operation_id", "desconocida")
                raise UnreconciledOperationException(
                    f"No se puede generar un plan residual: la operación {op_id} tiene estado incierto "
                    "y debe ser reconciliada antes de continuar."
                )

        # 3. Identificar operaciones y tareas ya aplicadas
        applied_ops = {
            entry["operation_id"]
            for entry in plan.operation_ledger
            if entry.get("status") == "applied" and entry.get("operation_id")
        }

        applied_task_ids: set[str] = set()
        for task in plan.tasks:
            task_id = task.get("id", "")
            if task.get("status") == "completed":
                applied_task_ids.add(task_id)
                continue

            op_ids = task.get("operation_ids", [])
            if op_ids and all(op in applied_ops for op in op_ids):
                applied_task_ids.add(task_id)

        # 4. Construir tareas residuales
        residual_tasks: list[dict[str, Any]] = []
        for task in plan.tasks:
            task_id = task.get("id", "")
            if task_id in applied_task_ids:
                continue

            # Clonar tarea y resetear a pending
            res_task = dict(task)
            res_task["status"] = "pending"
            res_task.pop("error_code", None)

            # Dependencias: filtrar las que ya fueron aplicadas
            prior_deps = task.get("depends_on", [])
            res_task["depends_on"] = [
                dep for dep in prior_deps if dep not in applied_task_ids
            ]

            # Operaciones: excluir las que ya fueron aplicadas
            prior_op_ids = task.get("operation_ids", [])
            res_task["operation_ids"] = [
                op for op in prior_op_ids if op not in applied_ops
            ]

            residual_tasks.append(res_task)

        if additional_request:
            mutation_ids = [task["id"] for task in residual_tasks if task["kind"] == "mutation"]
            task_kind = "mutation" if requires_mutation(additional_request) else "answer"
            task_id = "additional-request"
            while any(task["id"] == task_id for task in plan.tasks):
                task_id += "-new"
            if task_kind == "mutation":
                for task in residual_tasks:
                    if task["kind"] == "answer":
                        task["depends_on"].append(task_id)
            residual_tasks.append({
                "id": task_id,
                "objective": additional_request,
                "kind": task_kind,
                "depends_on": mutation_ids,
            })

        if not residual_tasks:
            return None

        # 5. Mantener en el ledger únicamente las operaciones aplicadas confirmadas
        confirmed_ledger = [
            dict(entry)
            for entry in plan.operation_ledger
            if entry.get("status") == "applied"
        ]

        goal = new_goal or f"Continuación: {plan.goal}"
        residual_plan = ExecutionPlan.create(
            goal=goal,
            tasks=residual_tasks,
            limits=dict(plan.limits),
        )
        residual_plan.operation_ledger = confirmed_ledger
        residual_plan.validate()
        return residual_plan
