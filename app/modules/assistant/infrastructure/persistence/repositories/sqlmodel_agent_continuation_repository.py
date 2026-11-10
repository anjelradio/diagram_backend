"""Implementación SQLModel del repositorio de continuaciones conversacionales."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update
from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.domain.repositories.agent_continuation_repository import (
    AgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.mappers.agent_continuation_mapper import (
    AgentContinuationMapper,
)
from app.modules.assistant.infrastructure.persistence.models.agent_continuation_model import (
    AgentContinuationModel,
)


class SQLModelAgentContinuationRepository(AgentContinuationRepository):
    """Acceso a datos persistidos de AgentContinuation mediante SQLModel/SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_id(self, continuation_id: UUID) -> AgentContinuation | None:
        statement = select(AgentContinuationModel).where(
            AgentContinuationModel.id == continuation_id,
            AgentContinuationModel.deleted_date.is_(None),
        )
        model = self.session.exec(statement).first()
        return AgentContinuationMapper.to_domain(model) if model else None

    def find_by_root_message_id(self, root_message_id: UUID) -> AgentContinuation | None:
        statement = select(AgentContinuationModel).where(
            AgentContinuationModel.root_message_id == root_message_id,
            AgentContinuationModel.deleted_date.is_(None),
        )
        model = self.session.exec(statement).first()
        return AgentContinuationMapper.to_domain(model) if model else None

    def find_active_by_scope(
        self,
        *,
        project_id: UUID,
        user_id: str,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        """Busca el único hilo de aclaración activo no expirado para el usuario y proyecto."""
        current_time = now or datetime.now(timezone.utc)
        statement = (
            select(AgentContinuationModel)
            .where(
                AgentContinuationModel.project_id == project_id,
                AgentContinuationModel.user_id == user_id,
                AgentContinuationModel.purpose == "clarification",
                AgentContinuationModel.state.in_(
                    [
                        ContinuationState.AWAITING_INPUT.value,
                        ContinuationState.READY.value,
                        ContinuationState.CLAIMED.value,
                    ]
                ),
                AgentContinuationModel.expires_at > current_time,
                AgentContinuationModel.deleted_date.is_(None),
            )
            .order_by(AgentContinuationModel.modified_date.desc(), AgentContinuationModel.id.desc())
            .limit(1)
        )
        model = self.session.exec(statement).first()
        return AgentContinuationMapper.to_domain(model) if model else None

    def expire_stale_active(
        self,
        *,
        project_id: UUID,
        user_id: str,
        now: datetime | None = None,
    ) -> int:
        """Expira hilos de aclaración activos o vencidos previos para garantizar unicidad al abrir uno nuevo."""
        current_time = now or datetime.now(timezone.utc)
        stmt = (
            update(AgentContinuationModel)
            .where(
                AgentContinuationModel.project_id == project_id,
                AgentContinuationModel.user_id == user_id,
                AgentContinuationModel.purpose == "clarification",
                AgentContinuationModel.state.in_(
                    [
                        ContinuationState.AWAITING_INPUT.value,
                        ContinuationState.READY.value,
                        ContinuationState.CLAIMED.value,
                    ]
                ),
                AgentContinuationModel.deleted_date.is_(None),
            )
            .values(
                state=ContinuationState.EXPIRED.value,
                close_reason="expired",
                modified_date=current_time,
            )
        )
        res = self.session.exec(stmt)
        return res.rowcount

    def list_active_candidates(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = 3,
        purpose: ContinuationPurpose | str | None = None,
        now: datetime | None = None,
    ) -> list[AgentContinuation]:
        current_time = now or datetime.now(timezone.utc)
        safe_limit = max(1, min(limit, 3))
        statement = select(AgentContinuationModel).where(
            AgentContinuationModel.project_id == project_id,
            AgentContinuationModel.user_id == user_id,
            AgentContinuationModel.state.in_(
                [ContinuationState.AWAITING_INPUT.value, ContinuationState.READY.value]
            ),
            AgentContinuationModel.expires_at > current_time,
            AgentContinuationModel.deleted_date.is_(None),
        )
        if purpose is not None:
            purpose_val = (
                purpose.value if isinstance(purpose, ContinuationPurpose) else str(purpose)
            )
            statement = statement.where(AgentContinuationModel.purpose == purpose_val)
        statement = statement.order_by(AgentContinuationModel.modified_date.desc()).limit(
            safe_limit
        )
        models = self.session.exec(statement).all()
        return [AgentContinuationMapper.to_domain(m) for m in models]

    def save(self, continuation: AgentContinuation) -> None:
        existing = self.session.get(AgentContinuationModel, continuation.id)
        if existing is None:
            if (
                continuation.purpose == ContinuationPurpose.CLARIFICATION
                and continuation.state in (
                    ContinuationState.AWAITING_INPUT,
                    ContinuationState.READY,
                    ContinuationState.CLAIMED,
                )
            ):
                self.expire_stale_active(
                    project_id=continuation.project_id,
                    user_id=continuation.user_id,
                )
                self.session.flush()
            model = AgentContinuationMapper.to_model(continuation)
            self.session.add(model)
        else:
            existing.latest_message_id = continuation.latest_message_id
            existing.state = continuation.state.value
            existing.version = continuation.version
            existing.effective_request = continuation.effective_request
            existing.resolved_facts = list(continuation.resolved_facts)
            existing.missing_fields = list(continuation.missing_fields)
            existing.outcome = continuation.outcome.value
            existing.purpose = continuation.purpose.value
            existing.close_reason = (
                continuation.close_reason.value
                if isinstance(continuation.close_reason, ContinuationCloseReason)
                else continuation.close_reason
            )
            existing.source_plan_message_id = continuation.source_plan_message_id
            existing.recent_message_ids = [str(item) for item in continuation.recent_message_ids]
            existing.image_context = continuation.image_context
            existing.dialog_state = continuation.dialog_state
            existing.expires_at = continuation.expires_at
            existing.claimed_by_message_id = continuation.claimed_by_message_id
            existing.modified_date = continuation.updated_date
            existing.deleted_date = continuation.deleted_date
            self.session.add(existing)

    def claim_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        by_message_id: UUID | None = None,
        new_message_id: UUID | None = None,
        user_id: str | None = None,
        project_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        target_msg_id = by_message_id or new_message_id
        if target_msg_id is None:
            raise ValueError("Debe especificarse by_message_id o new_message_id")
        current_time = now or datetime.now(timezone.utc)
        stmt = (
            update(AgentContinuationModel)
            .where(
                AgentContinuationModel.id == continuation_id,
                AgentContinuationModel.version == expected_version,
                AgentContinuationModel.state.in_(
                    [ContinuationState.AWAITING_INPUT.value, ContinuationState.READY.value]
                ),
                AgentContinuationModel.deleted_date.is_(None),
            )
            .values(
                state=ContinuationState.CLAIMED.value,
                version=expected_version + 1,
                claimed_by_message_id=target_msg_id,
                modified_date=current_time,
            )
        )
        result = self.session.exec(stmt)
        if result.rowcount == 0:
            existing = self.session.get(AgentContinuationModel, continuation_id)
            if (
                existing is not None
                and existing.claimed_by_message_id == target_msg_id
                and existing.state == ContinuationState.CLAIMED.value
            ):
                return AgentContinuationMapper.to_domain(existing)
            return None

        self.session.expire_all()
        updated = self.session.get(AgentContinuationModel, continuation_id)
        return AgentContinuationMapper.to_domain(updated) if updated else None

    def resolve_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        outcome: ContinuationOutcome = ContinuationOutcome.SUCCESS,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.RESOLVED,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        current_time = now or datetime.now(timezone.utc)
        reason_val = (
            close_reason.value
            if isinstance(close_reason, ContinuationCloseReason)
            else str(close_reason)
        )
        stmt = (
            update(AgentContinuationModel)
            .where(
                AgentContinuationModel.id == continuation_id,
                AgentContinuationModel.version == expected_version,
                AgentContinuationModel.state == ContinuationState.CLAIMED.value,
                AgentContinuationModel.deleted_date.is_(None),
            )
            .values(
                state=ContinuationState.RESOLVED.value,
                version=expected_version + 1,
                outcome=outcome.value,
                close_reason=reason_val,
                modified_date=current_time,
            )
        )
        result = self.session.exec(stmt)
        if result.rowcount == 0:
            return None

        self.session.expire_all()
        updated = self.session.get(AgentContinuationModel, continuation_id)
        return AgentContinuationMapper.to_domain(updated) if updated else None

    def close_claimed_by_message(
        self,
        *,
        message_id: UUID,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.CANCELLED,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        reason_val = (
            close_reason.value
            if isinstance(close_reason, ContinuationCloseReason)
            else str(close_reason)
        )
        target_state = (
            ContinuationState.RESOLVED.value
            if reason_val == "resolved"
            else ContinuationState.DECLINED.value
            if reason_val in ("declined", "cancelled", "topic_change")
            else ContinuationState.EXPIRED.value
        )
        stmt = (
            update(AgentContinuationModel)
            .where(
                AgentContinuationModel.claimed_by_message_id == message_id,
                AgentContinuationModel.state == ContinuationState.CLAIMED.value,
                AgentContinuationModel.deleted_date.is_(None),
            )
            .values(
                state=target_state,
                close_reason=reason_val,
                modified_date=current_time,
            )
        )
        result = self.session.exec(stmt)
        return result.rowcount
