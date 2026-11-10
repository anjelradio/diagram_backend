"""Entidad de dominio para la continuidad conversacional del asistente."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from app.modules.assistant.domain.exceptions import DomainException

MAX_ACTIVE_FACTS: int = 20
MAX_ACTIVE_QUESTIONS: int = 20
MAX_RECENT_MESSAGES: int = 10
MAX_EFFECTIVE_REQUEST_CHARS: int = 10_000
CONTINUATION_TTL_HOURS: int = 24


class ContinuationState(str, Enum):
    """Estados de negocio del ciclo de vida de una continuación."""

    AWAITING_INPUT = "awaiting_input"
    READY = "ready"
    CLAIMED = "claimed"
    RESOLVED = "resolved"
    DECLINED = "declined"
    EXPIRED = "expired"


class ContinuationPurpose(str, Enum):
    """Propósito explícito de la continuación."""

    CLARIFICATION = "clarification"
    RESIDUAL_RETRY = "residual_retry"


class ContinuationCloseReason(str, Enum):
    """Motivo de cierre de la continuación."""

    RESOLVED = "resolved"
    TOPIC_CHANGE = "topic_change"
    DECLINED = "declined"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class ContinuationOutcome(str, Enum):
    """Resultado final o intermedio del turno de continuación."""

    AWAITING_INPUT = "awaiting_input"
    PARTIAL = "partial"
    SUCCESS = "success"
    TECHNICAL_FAILURE = "technical_failure"


class AgentContinuation:
    """Entidad de dominio que conserva el contexto de solicitudes incompletas o parciales."""

    def __init__(
        self,
        *,
        id: UUID,
        project_id: UUID,
        user_id: str,
        root_message_id: UUID,
        latest_message_id: UUID,
        state: ContinuationState,
        version: int,
        effective_request: str,
        resolved_facts: tuple[dict[str, Any], ...],
        missing_fields: tuple[dict[str, Any], ...],
        outcome: ContinuationOutcome,
        purpose: ContinuationPurpose | str = ContinuationPurpose.CLARIFICATION,
        close_reason: ContinuationCloseReason | str | None = None,
        source_plan_message_id: UUID | None = None,
        recent_message_ids: tuple[UUID, ...] = (),
        image_context: dict[str, Any] | None = None,
        dialog_state: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        claimed_by_message_id: UUID | None = None,
        created_date: datetime | None = None,
        updated_date: datetime | None = None,
        deleted_date: datetime | None = None,
    ) -> None:
        self._validate_limits(
            effective_request=effective_request,
            resolved_facts=resolved_facts,
            missing_fields=missing_fields,
            recent_message_ids=recent_message_ids,
        )
        self.id = id
        self.project_id = project_id
        self.user_id = user_id
        self.root_message_id = root_message_id
        self.latest_message_id = latest_message_id
        self.state = state
        self.version = version
        self.effective_request = effective_request
        self.resolved_facts = resolved_facts
        self.missing_fields = missing_fields
        self.outcome = outcome
        self.purpose = (
            ContinuationPurpose(purpose)
            if isinstance(purpose, str)
            else purpose
        )
        self.close_reason = (
            ContinuationCloseReason(close_reason)
            if isinstance(close_reason, str) and close_reason in ContinuationCloseReason._value2member_map_
            else close_reason
        )
        self.source_plan_message_id = source_plan_message_id
        self.recent_message_ids = recent_message_ids
        self.image_context = image_context
        self.dialog_state = dialog_state
        self.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(hours=CONTINUATION_TTL_HOURS))
        self.claimed_by_message_id = claimed_by_message_id
        now = datetime.now(timezone.utc)
        self.created_date = created_date or now
        self.updated_date = updated_date or now
        self.deleted_date = deleted_date

    @staticmethod
    def _validate_limits(
        *,
        effective_request: str,
        resolved_facts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        missing_fields: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        recent_message_ids: tuple[UUID, ...] | list[UUID],
    ) -> None:
        if len(resolved_facts) > MAX_ACTIVE_FACTS:
            raise DomainException(
                f"La solicitud supera el límite de {MAX_ACTIVE_FACTS} hechos activos; debe dividirse."
            )
        if len(missing_fields) > MAX_ACTIVE_QUESTIONS:
            raise DomainException(
                f"La solicitud supera el límite de {MAX_ACTIVE_QUESTIONS} preguntas activas; debe dividirse."
            )
        if len(recent_message_ids) > MAX_RECENT_MESSAGES:
            raise DomainException(
                f"La continuación supera el límite de {MAX_RECENT_MESSAGES} mensajes recientes vinculados."
            )
        if len(effective_request) > MAX_EFFECTIVE_REQUEST_CHARS:
            raise DomainException(
                f"La solicitud efectiva supera el límite de {MAX_EFFECTIVE_REQUEST_CHARS} caracteres."
            )

    @classmethod
    def create(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        user_id: str,
        root_message_id: UUID,
        effective_request: str,
        resolved_facts: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        missing_fields: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        purpose: ContinuationPurpose | str = ContinuationPurpose.CLARIFICATION,
        close_reason: ContinuationCloseReason | str | None = None,
        source_plan_message_id: UUID | None = None,
        recent_message_ids: list[UUID] | tuple[UUID, ...] = (),
        image_context: dict[str, Any] | None = None,
        dialog_state: dict[str, Any] | None = None,
        outcome: ContinuationOutcome = ContinuationOutcome.AWAITING_INPUT,
        expires_at: datetime | None = None,
    ) -> AgentContinuation:
        """Constructor nombrado para iniciar una continuación válida."""
        state = (
            ContinuationState.READY
            if not missing_fields
            else ContinuationState.AWAITING_INPUT
        )
        return cls(
            id=id,
            project_id=project_id,
            user_id=user_id,
            root_message_id=root_message_id,
            latest_message_id=root_message_id,
            state=state,
            version=1,
            effective_request=effective_request.strip(),
            resolved_facts=tuple(resolved_facts),
            missing_fields=tuple(missing_fields),
            outcome=outcome,
            purpose=purpose,
            close_reason=close_reason,
            source_plan_message_id=source_plan_message_id,
            recent_message_ids=tuple(recent_message_ids),
            image_context=image_context,
            dialog_state=dialog_state,
            expires_at=expires_at,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Determina si la continuación ha superado su tiempo de vida."""
        current_time = now or datetime.now(timezone.utc)
        return current_time >= self.expires_at

    def apply_clarification(
        self,
        *,
        new_effective_request: str,
        resolved_facts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        remaining_missing_fields: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        latest_message_id: UUID,
        image_context: dict[str, Any] | None = None,
        dialog_state: dict[str, Any] | None = None,
    ) -> AgentContinuation:
        """Aplica una respuesta parcial o total del usuario actualizando el contexto."""
        if self.state not in (ContinuationState.AWAITING_INPUT, ContinuationState.READY):
            raise DomainException(f"No se puede actualizar una continuación en estado {self.state.value}.")

        next_recent = list(self.recent_message_ids)
        if latest_message_id not in next_recent:
            next_recent.append(latest_message_id)

        new_state = (
            ContinuationState.READY
            if not remaining_missing_fields
            else ContinuationState.AWAITING_INPUT
        )

        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=latest_message_id,
            state=new_state,
            version=self.version + 1,
            effective_request=new_effective_request.strip(),
            resolved_facts=tuple(resolved_facts),
            missing_fields=tuple(remaining_missing_fields),
            outcome=ContinuationOutcome.AWAITING_INPUT if remaining_missing_fields else ContinuationOutcome.SUCCESS,
            purpose=self.purpose,
            close_reason=None,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=tuple(next_recent),
            image_context=image_context or self.image_context,
            dialog_state=dialog_state or self.dialog_state,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=CONTINUATION_TTL_HOURS),
            claimed_by_message_id=None,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

    def claim(self, *, by_message_id: UUID, expected_version: int) -> AgentContinuation:
        """Reclama la continuación atómicamente verificando versión optimista."""
        if self.version != expected_version:
            raise DomainException(
                f"Conflicto de versión en continuación: esperada {expected_version}, actual {self.version}."
            )
        if self.state not in (ContinuationState.AWAITING_INPUT, ContinuationState.READY):
            raise DomainException(
                f"No se puede reclamar una continuación en estado {self.state.value}."
            )

        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=self.latest_message_id,
            state=ContinuationState.CLAIMED,
            version=self.version + 1,
            effective_request=self.effective_request,
            resolved_facts=self.resolved_facts,
            missing_fields=self.missing_fields,
            outcome=self.outcome,
            purpose=self.purpose,
            close_reason=None,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=self.recent_message_ids,
            image_context=self.image_context,
            dialog_state=self.dialog_state,
            expires_at=self.expires_at,
            claimed_by_message_id=by_message_id,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

    def resolve(
        self,
        *,
        outcome: ContinuationOutcome = ContinuationOutcome.SUCCESS,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.RESOLVED,
    ) -> AgentContinuation:
        """Marca la continuación como finalizada exitosamente."""
        if self.state != ContinuationState.CLAIMED:
            raise DomainException(
                f"Solo se puede resolver una continuación previamente reclamada (estado actual: {self.state.value})."
            )

        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=self.latest_message_id,
            state=ContinuationState.RESOLVED,
            version=self.version + 1,
            effective_request=self.effective_request,
            resolved_facts=self.resolved_facts,
            missing_fields=(),
            outcome=outcome,
            purpose=self.purpose,
            close_reason=close_reason,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=self.recent_message_ids,
            image_context=self.image_context,
            dialog_state=self.dialog_state,
            expires_at=self.expires_at,
            claimed_by_message_id=self.claimed_by_message_id,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

    def decline(
        self,
        *,
        reason: ContinuationCloseReason | str = ContinuationCloseReason.DECLINED,
    ) -> AgentContinuation:
        """Cierra la continuación cuando el usuario desiste o declina continuar."""
        if self.state in (ContinuationState.RESOLVED, ContinuationState.DECLINED):
            raise DomainException(f"La continuación ya está cerrada ({self.state.value}).")

        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=self.latest_message_id,
            state=ContinuationState.DECLINED,
            version=self.version + 1,
            effective_request=self.effective_request,
            resolved_facts=self.resolved_facts,
            missing_fields=(),
            outcome=self.outcome,
            purpose=self.purpose,
            close_reason=reason,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=self.recent_message_ids,
            image_context=self.image_context,
            dialog_state=self.dialog_state,
            expires_at=self.expires_at,
            claimed_by_message_id=self.claimed_by_message_id,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

    def expire(
        self,
        *,
        reason: ContinuationCloseReason | str = ContinuationCloseReason.EXPIRED,
    ) -> AgentContinuation:
        """Marca la continuación como expirada para evitar candidatos duplicados u obsoletos."""
        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=self.latest_message_id,
            state=ContinuationState.EXPIRED,
            version=self.version + 1,
            effective_request=self.effective_request,
            resolved_facts=self.resolved_facts,
            missing_fields=(),
            outcome=self.outcome,
            purpose=self.purpose,
            close_reason=reason,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=self.recent_message_ids,
            image_context=self.image_context,
            dialog_state=self.dialog_state,
            expires_at=datetime.now(timezone.utc),
            claimed_by_message_id=self.claimed_by_message_id,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

    def close(
        self,
        reason: ContinuationCloseReason | str = ContinuationCloseReason.RESOLVED,
        *,
        outcome: ContinuationOutcome = ContinuationOutcome.AWAITING_INPUT,
    ) -> AgentContinuation:
        """Cierra el hilo con un motivo explícito (ej. topic_change, cancelled, expired, declined)."""
        close_reason_val = (
            ContinuationCloseReason(reason)
            if isinstance(reason, str) and reason in ContinuationCloseReason._value2member_map_
            else reason
        )
        if close_reason_val == ContinuationCloseReason.RESOLVED:
            target_state = ContinuationState.RESOLVED
        elif close_reason_val in (
            ContinuationCloseReason.DECLINED,
            ContinuationCloseReason.TOPIC_CHANGE,
            ContinuationCloseReason.CANCELLED,
            ContinuationCloseReason.ABANDONED,
        ):
            target_state = ContinuationState.DECLINED
        else:
            target_state = ContinuationState.EXPIRED

        return AgentContinuation(
            id=self.id,
            project_id=self.project_id,
            user_id=self.user_id,
            root_message_id=self.root_message_id,
            latest_message_id=self.latest_message_id,
            state=target_state,
            version=self.version + 1,
            effective_request=self.effective_request,
            resolved_facts=self.resolved_facts,
            missing_fields=(),
            outcome=outcome,
            purpose=self.purpose,
            close_reason=close_reason_val,
            source_plan_message_id=self.source_plan_message_id,
            recent_message_ids=self.recent_message_ids,
            image_context=self.image_context,
            dialog_state=self.dialog_state,
            expires_at=datetime.now(timezone.utc),
            claimed_by_message_id=self.claimed_by_message_id,
            created_date=self.created_date,
            updated_date=datetime.now(timezone.utc),
            deleted_date=self.deleted_date,
        )

