"""Modelo puro y versionado del progreso de una ejecución del agente."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.modules.assistant.domain.exceptions import (
    ExecutionPlanErrorReason,
    InvalidExecutionPlanException,
)

PLAN_VERSION = 1
PLAN_STATUSES = {"pending", "running", "completed", "partial", "failed", "uncertain"}
TASK_STATUSES = {"pending", "running", "completed", "failed", "blocked", "uncertain"}
OPERATION_STATUSES = {"proposed", "validated", "applied", "rejected", "uncertain"}


@dataclass(slots=True)
class ExecutionPlan:
    """Plan acotado con dependencias y resultados confirmados por operación."""

    goal: str
    tasks: list[dict[str, Any]]
    status: str = "pending"
    version: int = PLAN_VERSION
    operation_ledger: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    @classmethod
    def create(
        cls,
        *,
        goal: str,
        tasks: list[dict[str, Any]],
        limits: dict[str, int] | None = None,
    ) -> ExecutionPlan:
        normalized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            item = dict(task)
            item.setdefault("id", str(uuid4()))
            item.setdefault("kind", "mutation")
            item.setdefault("depends_on", [])
            item.setdefault("status", "pending")
            item.setdefault("operation_ids", [])
            item.setdefault("result_refs", [])
            normalized_tasks.append(item)
        plan = cls(goal=goal.strip(), tasks=normalized_tasks, limits=limits or {})
        plan.validate()
        return plan

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExecutionPlan:
        try:
            plan = cls(
                version=value["version"],
                goal=value["goal"],
                status=value["status"],
                tasks=[dict(item) for item in value["tasks"]],
                operation_ledger=[dict(item) for item in value["operation_ledger"]],
                limits=dict(value["limits"]),
                created_at=value["created_at"],
                updated_at=value["updated_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_SERIALIZED) from exc
        plan.validate()
        return plan

    def validate(self) -> None:
        if self.version != PLAN_VERSION or self.status not in PLAN_STATUSES:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_VERSION_OR_STATUS)
        if not isinstance(self.goal, str) or not self.goal.strip() or len(self.goal) > 2_000:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_GOAL)
        if not self.tasks or len(self.tasks) > 50 or len(self.operation_ledger) > 500:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_LIMIT_EXCEEDED)
        task_ids = [task.get("id") for task in self.tasks]
        if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK_ID)
        if len(set(task_ids)) != len(task_ids):
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_DUPLICATE_TASK_ID)
        known_ids = set(task_ids)
        dependencies: dict[str, set[str]] = {}
        for task in self.tasks:
            task_id = task["id"]
            depends_on = task.get("depends_on", [])
            result_refs = task.get("result_refs", [])
            expected_actions = task.get("expected_actions", [])
            if (
                task.get("status") not in TASK_STATUSES
                or task.get("kind") not in {"mutation", "answer"}
                or not isinstance(task.get("objective"), str)
                or not task["objective"].strip()
                or not isinstance(depends_on, list)
                or not all(isinstance(dependency_id, str) for dependency_id in depends_on)
                or not isinstance(result_refs, list)
                or not isinstance(expected_actions, list)
                or len(expected_actions) > 100
                or any(
                    not (
                        (isinstance(action, str) and bool(action))
                        or (
                            isinstance(action, dict)
                            and isinstance(action.get("kind"), str)
                            and bool(action["kind"])
                            and ("name" not in action or isinstance(action["name"], str))
                        )
                    )
                    for action in expected_actions
                )
                or (expected_actions and task.get("kind") != "mutation")
                or any(
                    not isinstance(ref, dict) or not ref.get("id") or not ref.get("type")
                    for ref in result_refs
                )
            ):
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK)
            error_code = task.get("error_code")
            failure_reason = task.get("failure_reason")
            if error_code is not None and (
                not isinstance(error_code, str) or not error_code.strip()
            ):
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK)
            if failure_reason is not None and (
                not isinstance(failure_reason, str) or not failure_reason.strip()
            ):
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK)
            dependency_ids = set(depends_on)
            if task_id in dependency_ids or not dependency_ids <= known_ids:
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_DEPENDENCY)
            dependencies[task_id] = dependency_ids

        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_CYCLIC_DEPENDENCY)
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency_id in dependencies[task_id]:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in known_ids:
            visit(task_id)

        for entry in self.operation_ledger:
            if (
                not isinstance(entry.get("operation_id"), str)
                or not entry["operation_id"].strip()
                or entry.get("status") not in OPERATION_STATUSES
            ):
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_OPERATION)
            entity_refs = entry.get("entity_refs", [])
            if not isinstance(entity_refs, list) or any(
                not isinstance(ref, dict) or not ref.get("id") or not ref.get("type")
                for ref in entity_refs
            ):
                raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_OPERATION)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Devuelve una tarea del plan por su identificador."""
        return next((task for task in self.tasks if task.get("id") == task_id), None)

    def get_ancestor_task_ids(self, task_id: str) -> set[str]:
        """Obtiene recursivamente todos los identificadores de tareas antecesoras."""
        ancestors: set[str] = set()
        task = self.get_task(task_id)
        if not task:
            return ancestors
        to_visit = list(task.get("depends_on", []))
        while to_visit:
            current_id = to_visit.pop()
            if current_id not in ancestors:
                ancestors.add(current_id)
                curr_task = self.get_task(current_id)
                if curr_task:
                    to_visit.extend(curr_task.get("depends_on", []))
        return ancestors

    def get_descendant_task_ids(self, task_id: str) -> set[str]:
        """Obtiene recursivamente todos los identificadores de tareas descendientes."""
        descendants: set[str] = set()
        to_check = [task_id]
        while to_check:
            parent_id = to_check.pop()
            for task in self.tasks:
                current_id = task["id"]
                if parent_id in task.get("depends_on", []) and current_id not in descendants:
                    descendants.add(current_id)
                    to_check.append(current_id)
        return descendants

    def block_descendants(self, failed_task_id: str) -> list[str]:
        """Bloquea en cascada todas las tareas pendientes dependientes de una tarea fallida."""
        blocked_ids: list[str] = []
        descendants = self.get_descendant_task_ids(failed_task_id)
        for task in self.tasks:
            if task["id"] in descendants and task.get("status") == "pending":
                task["status"] = "blocked"
                task["error_code"] = f"blocked_by_{failed_task_id}"
                blocked_ids.append(task["id"])
        if blocked_ids:
            self.updated_at = _now()
        return blocked_ids

    def mark_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error_code: str | None = None,
        failure_reason: str | None = None,
        result_refs: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Actualiza el estado de una tarea y bloquea descendientes si falló o es incierta."""
        if status not in TASK_STATUSES:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK)
        task = self.get_task(task_id)
        if task is None:
            raise InvalidExecutionPlanException(reason=ExecutionPlanErrorReason.PLAN_INVALID_TASK_ID)

        task["status"] = status
        if error_code is not None:
            task["error_code"] = error_code
        if failure_reason is not None:
            task["failure_reason"] = failure_reason
        if result_refs is not None:
            task["result_refs"] = result_refs
        self.updated_at = _now()

        blocked_ids: list[str] = []
        if status in {"failed", "uncertain"}:
            blocked_ids = self.block_descendants(task_id)
        self.recompute_overall_status()
        return blocked_ids

    def are_prerequisites_met(self, task_id: str) -> bool:
        """Indica si todos los prerequisitos de la tarea fueron completados con éxito."""
        task = self.get_task(task_id)
        if not task:
            return False
        for dep_id in task.get("depends_on", []):
            dep_task = self.get_task(dep_id)
            if not dep_task or dep_task.get("status") != "completed":
                return False
        return True

    def is_task_ready(self, task_id: str) -> bool:
        """Indica si una tarea está lista para ejecutarse (pendiente y prerequisitos cumplidos)."""
        task = self.get_task(task_id)
        if not task or task.get("status") != "pending":
            return False
        return self.are_prerequisites_met(task_id)

    def get_ready_tasks(self) -> list[dict[str, Any]]:
        """Devuelve todas las tareas pendientes cuyos prerequisitos ya están completados."""
        return [task for task in self.tasks if self.is_task_ready(task["id"])]

    def get_confirmed_entity_refs(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """Extrae únicamente referencias confirmadas ('applied') de operaciones relevantes."""
        relevant_task_ids: set[str] | None = None
        if task_id is not None:
            relevant_task_ids = self.get_ancestor_task_ids(task_id)

        seen: set[tuple[str, str]] = set()
        confirmed: list[dict[str, Any]] = []
        for entry in self.operation_ledger:
            if entry.get("status") != "applied":
                continue
            entry_task_id = entry.get("task_id")
            if relevant_task_ids is not None and entry_task_id not in relevant_task_ids:
                continue
            for ref in entry.get("entity_refs", []):
                key = (str(ref.get("type")), str(ref.get("id")))
                if key not in seen:
                    seen.add(key)
                    confirmed.append(dict(ref))
        return confirmed

    def recompute_overall_status(self) -> str:
        """Recalcula el estado general del plan a partir de las tareas y el ledger."""
        has_uncertain = (
            any(task.get("status") == "uncertain" for task in self.tasks)
            or any(entry.get("status") == "uncertain" for entry in self.operation_ledger)
        )
        if has_uncertain:
            self.status = "uncertain"
            return self.status

        all_completed = bool(self.tasks) and all(task.get("status") == "completed" for task in self.tasks)
        if all_completed:
            self.status = "completed"
            return self.status

        if any(task.get("status") == "running" for task in self.tasks):
            self.status = "running"
            return self.status

        completed_count = sum(1 for task in self.tasks if task.get("status") == "completed")
        failed_or_blocked = sum(1 for task in self.tasks if task.get("status") in {"failed", "blocked"})
        pending_count = sum(1 for task in self.tasks if task.get("status") == "pending")

        if pending_count == 0:
            if completed_count > 0 and failed_or_blocked > 0:
                self.status = "partial"
                return self.status
            if completed_count == 0 and failed_or_blocked > 0:
                self.status = "failed"
                return self.status

        ready_tasks = self.get_ready_tasks()
        if not ready_tasks and pending_count > 0:
            if completed_count > 0:
                self.status = "partial"
                return self.status
            if failed_or_blocked > 0:
                self.status = "failed"
                return self.status

        return self.status

    def to_dict(self) -> dict[str, Any]:
        self.updated_at = _now()
        self.validate()
        return {
            "version": self.version,
            "goal": self.goal,
            "status": self.status,
            "tasks": self.tasks,
            "operation_ledger": self.operation_ledger,
            "limits": self.limits,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
