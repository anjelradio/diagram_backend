"""Mutación pura del ledger persistido dentro de AgentMessage.plan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.modules.assistant.domain.entities.execution_plan import (
    OPERATION_STATUSES,
    ExecutionPlan,
)


class OperationLedger:
    """Añade evidencia propuesta/confirmada sin acceder a la base de datos."""

    VALID_STATUSES = OPERATION_STATUSES

    @staticmethod
    def record(
        plan: ExecutionPlan,
        *,
        operation_id: str,
        task_id: str,
        tool_name: str,
        input_digest: str,
        event: dict[str, Any],
    ) -> None:
        raw_status = event.get("status", "validated")
        if raw_status not in OPERATION_STATUSES:
            raise ValueError(f"Estado de operación inválido: {raw_status}")

        entry = next(
            (
                item
                for item in plan.operation_ledger
                if item.get("operation_id") == operation_id
            ),
            None,
        )
        if entry is None:
            entry = {
                "operation_id": operation_id,
                "task_id": task_id,
                "tool_name": tool_name,
                "action_kind": event.get("action_kind"),
                "target_name": event.get("target_name"),
                "input_digest": input_digest,
                "status": "proposed",
                "entity_refs": [],
                "derived_effects": [],
            }
            plan.operation_ledger.append(entry)

        # Regla de integridad: Una operación confirmada ('applied') no puede
        # degradarse a 'proposed', 'validated' ni 'rejected'.
        if entry.get("status") == "applied" and raw_status in {"proposed", "validated", "rejected"}:
            return

        entry["status"] = raw_status
        if event.get("action_kind") and not entry.get("action_kind"):
            entry["action_kind"] = event["action_kind"]
        if event.get("target_name") and not entry.get("target_name"):
            entry["target_name"] = str(event["target_name"])

        if "entity_refs" in event and event["entity_refs"] is not None:
            raw_refs = event["entity_refs"]
            if isinstance(raw_refs, list):
                normalized_refs = []
                for ref in raw_refs:
                    if isinstance(ref, dict) and ref.get("type"):
                        ref_id = str(ref.get("id") or ref.get("name") or "")
                        if ref_id:
                            normalized_ref: dict[str, str] = {
                                "type": str(ref["type"]),
                                "id": ref_id,
                            }
                            if ref.get("name"):
                                normalized_ref["name"] = str(ref["name"])
                            normalized_refs.append(normalized_ref)
                entry["entity_refs"] = normalized_refs

        if "derived_effects" in event and event["derived_effects"] is not None:
            raw_effects = event["derived_effects"]
            if isinstance(raw_effects, list):
                entry["derived_effects"] = [
                    dict(eff) for eff in raw_effects if isinstance(eff, dict)
                ]

        if event.get("error_code"):
            entry["error_code"] = str(event["error_code"])

        if raw_status == "applied":
            entry.setdefault("committed_at", datetime.now(timezone.utc).isoformat())

    @staticmethod
    def get_operations_by_status(
        plan: ExecutionPlan, status: str
    ) -> list[dict[str, Any]]:
        return [
            entry
            for entry in plan.operation_ledger
            if entry.get("status") == status
        ]

    @staticmethod
    def has_uncertain_operations(plan: ExecutionPlan) -> bool:
        return any(
            entry.get("status") == "uncertain"
            for entry in plan.operation_ledger
        )

    @staticmethod
    def has_applied_operations(plan: ExecutionPlan) -> bool:
        return any(
            entry.get("status") == "applied"
            for entry in plan.operation_ledger
        )

