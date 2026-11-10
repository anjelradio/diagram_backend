"""Marcadores acotados para continuar una interpretación visual pendiente."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.modules.assistant.application.services.visual.visual_contracts import VisualIntent

CLARIFICATION_VERSION = 1
CLARIFICATION_TTL = timedelta(hours=24)
MAX_CLARIFICATION_CHARS = 500


def create_visual_clarification(
    *,
    message_id: UUID,
    project_id: UUID,
    user_id: str,
    prompt: str,
    image_url: str,
    intent: VisualIntent,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construye metadata JSON versionada sin persistir el plan de ejecución."""
    timestamp = now or datetime.now(timezone.utc)
    question = (intent.clarification or "¿Qué parte del diagrama quieres usar?").strip()
    if len(question) > MAX_CLARIFICATION_CHARS:
        question = question[:MAX_CLARIFICATION_CHARS]
    return {
        "kind": "visual_clarification",
        "version": CLARIFICATION_VERSION,
        "message_id": str(message_id),
        "project_id": str(project_id),
        "user_id": user_id,
        "original_prompt": prompt[:10_000],
        "image_url": image_url[:2_048],
        "question": question,
        "intent": intent.to_prompt_payload(),
        "requested_mode": intent.requested_mode,
        "created_at": timestamp.isoformat(),
        "expires_at": (timestamp + CLARIFICATION_TTL).isoformat(),
        "claimed_by": None,
    }


def is_valid_visual_clarification(
    marker: Any,
    *,
    user_id: str,
    project_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Comprueba formato, identidad y vigencia antes de reusar una imagen."""
    if not isinstance(marker, dict):
        return False
    if (
        marker.get("kind") != "visual_clarification"
        or marker.get("version") != CLARIFICATION_VERSION
        or marker.get("user_id") != user_id
        or marker.get("project_id") != str(project_id)
        or marker.get("claimed_by") is not None
        or not isinstance(marker.get("image_url"), str)
        or not marker["image_url"].startswith("https://")
        or not isinstance(marker.get("original_prompt"), str)
        or not isinstance(marker.get("question"), str)
    ):
        return False
    try:
        expires_at = datetime.fromisoformat(marker["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False
    timestamp = now or datetime.now(timezone.utc)
    return expires_at > timestamp


def is_explicit_deletion_confirmation(answer: str) -> bool:
    """Acepta solo respuestas afirmativas inequívocas a la confirmación de borrado."""
    normalized = " ".join(answer.strip().casefold().split())
    if not normalized or re.search(r"\b(no|cancel|cancelar|detener|stop)\b", normalized):
        return False
    return normalized in {
        "sí",
        "si",
        "sí, confirmo",
        "si confirmo",
        "confirmo",
        "confirmo la eliminación",
        "confirmo eliminar",
        "confirmo el borrado",
        "confirmar",
        "confirm",
        "yes",
        "yes, confirm",
        "i confirm",
    }


def adapt_visual_clarification_to_continuation(
    marker: dict[str, Any],
    *,
    continuation_id: UUID | None = None,
) -> Any:
    """Adapta un marcador legacy de visual_clarification a AgentContinuation conservando imagen, exclusiones, selecciones y borrado."""
    from app.modules.assistant.domain.entities.agent_continuation import (
        AgentContinuation,
        ContinuationOutcome,
        ContinuationState,
    )

    msg_id = UUID(str(marker["message_id"]))
    project_id = UUID(str(marker["project_id"]))
    user_id = str(marker["user_id"])
    claimed_by_str = marker.get("claimed_by")
    claimed_by_id = UUID(str(claimed_by_str)) if claimed_by_str else None

    state = ContinuationState.CLAIMED if claimed_by_id else ContinuationState.AWAITING_INPUT
    version = 1

    try:
        expires_at = datetime.fromisoformat(marker["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        expires_at = datetime.now(timezone.utc) + CLARIFICATION_TTL

    image_context = {
        "image_url": marker.get("image_url"),
        "question": marker.get("question"),
        "intent": marker.get("intent"),
        "requested_mode": marker.get("requested_mode"),
        "requires_deletion_confirmation": marker.get("requires_deletion_confirmation", False),
        "class_ambiguity": marker.get("class_ambiguity"),
        "selected_class_ids": marker.get("selected_class_ids", {}),
        "exclusions": marker.get("exclusions", []),
        "legacy_message_id": str(msg_id),
    }

    missing_fields = []
    if marker.get("question"):
        missing_fields.append({"key": "visual_clarification", "question": marker["question"]})

    return AgentContinuation(
        id=continuation_id or msg_id,
        project_id=project_id,
        user_id=user_id,
        root_message_id=msg_id,
        latest_message_id=msg_id,
        state=state,
        version=version,
        effective_request=marker.get("original_prompt", ""),
        resolved_facts=[],
        missing_fields=missing_fields,
        outcome=ContinuationOutcome.AWAITING_INPUT,
        source_plan_message_id=None,
        recent_message_ids=[msg_id],
        image_context=image_context,
        expires_at=expires_at,
        claimed_by_message_id=claimed_by_id,
    )
