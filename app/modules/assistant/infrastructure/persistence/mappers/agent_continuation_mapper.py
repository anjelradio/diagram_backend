"""Mapper bidireccional entre la entidad de dominio AgentContinuation y AgentContinuationModel."""

from __future__ import annotations

from uuid import UUID

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.infrastructure.persistence.models.agent_continuation_model import (
    AgentContinuationModel,
)


class AgentContinuationMapper:
    """Convierte continuaciones entre el modelo relacional y la entidad pura de dominio."""

    @staticmethod
    def to_model(entity: AgentContinuation) -> AgentContinuationModel:
        return AgentContinuationModel(
            id=entity.id,
            project_id=entity.project_id,
            user_id=entity.user_id,
            root_message_id=entity.root_message_id,
            latest_message_id=entity.latest_message_id,
            state=entity.state.value,
            version=entity.version,
            effective_request=entity.effective_request,
            resolved_facts=list(entity.resolved_facts),
            missing_fields=list(entity.missing_fields),
            outcome=entity.outcome.value,
            purpose=entity.purpose.value,
            close_reason=entity.close_reason.value if isinstance(entity.close_reason, ContinuationCloseReason) else entity.close_reason,
            source_plan_message_id=entity.source_plan_message_id,
            recent_message_ids=[str(item) for item in entity.recent_message_ids],
            image_context=entity.image_context,
            dialog_state=entity.dialog_state,
            expires_at=entity.expires_at,
            claimed_by_message_id=entity.claimed_by_message_id,
            created_date=entity.created_date,
            modified_date=entity.updated_date,
            deleted_date=entity.deleted_date,
        )

    @staticmethod
    def to_domain(model: AgentContinuationModel) -> AgentContinuation:
        recent_ids = tuple(
            UUID(item) if isinstance(item, str) else item
            for item in (model.recent_message_ids or [])
        )
        return AgentContinuation(
            id=model.id,
            project_id=model.project_id,
            user_id=model.user_id,
            root_message_id=model.root_message_id,
            latest_message_id=model.latest_message_id,
            state=ContinuationState(model.state),
            version=model.version,
            effective_request=model.effective_request,
            resolved_facts=tuple(model.resolved_facts or []),
            missing_fields=tuple(model.missing_fields or []),
            outcome=ContinuationOutcome(model.outcome),
            purpose=ContinuationPurpose(getattr(model, "purpose", None) or "clarification"),
            close_reason=getattr(model, "close_reason", None),
            source_plan_message_id=model.source_plan_message_id,
            recent_message_ids=recent_ids,
            image_context=model.image_context,
            dialog_state=model.dialog_state,
            expires_at=model.expires_at,
            claimed_by_message_id=model.claimed_by_message_id,
            created_date=model.created_date,
            updated_date=model.modified_date,
            deleted_date=model.deleted_date,
        )
