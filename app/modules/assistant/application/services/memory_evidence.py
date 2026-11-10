"""Proyección acotada y segura de operaciones confirmadas en el operation_ledger."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

_ACTION_KIND_LABELS: dict[str, str] = {
    "CREATE_CLASS": "Creación de clase",
    "RENAME_CLASS": "Renombrado de clase",
    "DELETE_CLASS": "Eliminación de clase",
    "MOVE_CLASS": "Movimiento de clase",
    "CREATE_ATTRIBUTE": "Creación de atributo",
    "UPDATE_ATTRIBUTE": "Modificación de atributo",
    "DELETE_ATTRIBUTE": "Eliminación de atributo",
    "REPOSITION_ATTRIBUTE": "Reposicionamiento de atributo",
    "CREATE_RELATION": "Creación de relación",
    "RENAME_RELATION": "Renombrado de relación",
    "DELETE_RELATION": "Eliminación de relación",
}


@dataclass(frozen=True, slots=True)
class ConfirmedOperation:
    """Representa una mutación confirmada (status=applied) en el operation_ledger."""

    operation_id: str
    action_kind: str
    entity_refs: tuple[dict[str, str], ...] = field(default_factory=tuple)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action_kind": self.action_kind,
            "entity_refs": [dict(ref) for ref in self.entity_refs],
            "summary": self.summary,
        }


def _format_operation_summary(action_kind: str, entity_refs: list[dict[str, str]]) -> str:
    """Genera un resumen legible sin exponer UUIDs a menos que no haya otro dato."""
    label = _ACTION_KIND_LABELS.get(action_kind, action_kind or "Operación")
    names: list[str] = []
    for ref in entity_refs:
        name = ref.get("name")
        if name and not _UUID_PATTERN.search(str(name)):
            names.append(str(name))
        elif ref.get("type"):
            ref_id = ref.get("id") or ""
            if ref_id and not _UUID_PATTERN.search(str(ref_id)):
                names.append(f"{ref['type']} {ref_id}")
            else:
                names.append(str(ref["type"]))

    if names:
        return f"{label}: {', '.join(names)}"
    return label


def extract_confirmed_operations(
    plan_or_ledger: Any,
    max_operations: int = 50,
) -> list[ConfirmedOperation]:
    """Extrae únicamente operaciones con status='applied' del operation_ledger.

    Descarta estrictamente operaciones en status 'proposed', 'validated',
    'rejected', 'failed', 'uncertain' o cualquier otro estado no confirmado.
    """
    if plan_or_ledger is None:
        return []

    raw_ledger: list[Any] = []
    if isinstance(plan_or_ledger, list):
        raw_ledger = plan_or_ledger
    elif isinstance(plan_or_ledger, dict):
        raw_ledger = plan_or_ledger.get("operation_ledger") or []
    elif hasattr(plan_or_ledger, "operation_ledger"):
        raw_ledger = getattr(plan_or_ledger, "operation_ledger") or []

    if not isinstance(raw_ledger, list):
        return []

    confirmed: list[ConfirmedOperation] = []
    for entry in raw_ledger:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "applied":
            continue

        op_id = str(entry.get("operation_id") or "")
        action_kind = str(entry.get("action_kind") or "UNKNOWN")
        raw_refs = entry.get("entity_refs") or []

        cleaned_refs: list[dict[str, str]] = []
        if isinstance(raw_refs, list):
            for ref in raw_refs:
                if not isinstance(ref, dict):
                    continue
                cleaned_ref: dict[str, str] = {}
                if ref.get("type"):
                    cleaned_ref["type"] = str(ref["type"])
                if ref.get("name"):
                    cleaned_ref["name"] = str(ref["name"])
                if ref.get("id"):
                    cleaned_ref["id"] = str(ref["id"])
                if cleaned_ref:
                    cleaned_refs.append(cleaned_ref)

        summary = _format_operation_summary(action_kind, cleaned_refs)

        confirmed.append(
            ConfirmedOperation(
                operation_id=op_id,
                action_kind=action_kind,
                entity_refs=tuple(cleaned_refs),
                summary=summary,
            )
        )
        if len(confirmed) >= max_operations:
            break

    return confirmed


def format_confirmed_operations_text(operations: list[ConfirmedOperation]) -> str:
    """Devuelve un resumen en texto plano/markdown para ser consumido por el compactador de memoria."""
    if not operations:
        return "Sin operaciones de modificación confirmadas."
    lines: list[str] = []
    for op in operations:
        lines.append(f"- {op.summary}")
    return "\n".join(lines)
