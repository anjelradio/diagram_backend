"""Puerto de repositorio para la entidad de dominio AgentContinuation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
)


class AgentContinuationRepository(ABC):
    """Contrato de persistencia y reclamo optimista para continuaciones conversacionales."""

    @abstractmethod
    def find_by_id(self, continuation_id: UUID) -> AgentContinuation | None:
        """Busca una continuación por su identificador único."""

    @abstractmethod
    def find_by_root_message_id(self, root_message_id: UUID) -> AgentContinuation | None:
        """Busca una continuación por el ID de su mensaje raíz."""

    @abstractmethod
    def find_active_by_scope(
        self,
        *,
        project_id: UUID,
        user_id: str,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        """Busca el único hilo de aclaración activo no expirado para el usuario y proyecto."""

    @abstractmethod
    def list_active_candidates(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = 3,
        purpose: ContinuationPurpose | str | None = None,
        now: datetime | None = None,
    ) -> list[AgentContinuation]:
        """Lista hasta N continuaciones abiertas no expiradas del usuario y proyecto."""

    @abstractmethod
    def save(self, continuation: AgentContinuation) -> None:
        """Guarda o actualiza la continuación en la sesión actual."""

    @abstractmethod
    def claim_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        by_message_id: UUID,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        """Reclama la continuación atómicamente por versión esperada (CAS). Retorna None si hay conflicto."""

    @abstractmethod
    def resolve_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        outcome: ContinuationOutcome = ContinuationOutcome.SUCCESS,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.RESOLVED,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        """Resuelve la continuación verificando la versión optimista y asignando motivo de cierre."""

    @abstractmethod
    def close_claimed_by_message(
        self,
        *,
        message_id: UUID,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.CANCELLED,
        now: datetime | None = None,
    ) -> int:
        """Cierra de forma atómica cualquier continuación reclamada por el mensaje indicado."""

    def find_active_candidates(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = 3,
        purpose: ContinuationPurpose | str | None = None,
        now: datetime | None = None,
    ) -> list[AgentContinuation]:
        """Alias para list_active_candidates."""
        return self.list_active_candidates(
            project_id=project_id, user_id=user_id, limit=limit, purpose=purpose, now=now
        )

    def resolve(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        outcome: ContinuationOutcome = ContinuationOutcome.SUCCESS,
        latest_message_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        """Alias para resolve_atomic."""
        return self.resolve_atomic(continuation_id=continuation_id, expected_version=expected_version, outcome=outcome, now=now)
