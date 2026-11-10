from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from app.modules.assistant.domain.entities.agent_message import AgentMessage


class AgentMessageRepository(ABC):
    """Persistencia de mensajes y su regla de ejecución por usuario/proyecto."""

    @abstractmethod
    def find_by_id(self, message_id: UUID) -> AgentMessage | None:
        """Busca un mensaje activo por UUID."""

    @abstractmethod
    def save_new(self, message: AgentMessage) -> None:
        """Guarda un mensaje running o rechaza si su autor ya tiene uno activo."""

    @abstractmethod
    def claim_next(self, *, worker_id: str, now: datetime, lease_until: datetime) -> AgentMessage | None:
        """Reclama atómicamente un mensaje running sin lease vigente."""

    @abstractmethod
    def renew_lease(self, *, message_id: UUID, worker_id: str, now: datetime, lease_until: datetime) -> bool:
        """Renueva solo el lease que pertenece al worker indicado."""

    @abstractmethod
    def is_cancel_requested(self, message_id: UUID) -> bool:
        """Lee la marca de cancelación directamente de la persistencia."""

    @abstractmethod
    def request_cancel(self, *, message_id: UUID, project_id: UUID, user_id: str, now: datetime) -> AgentMessage | None:
        """Solicita cancelar solo una ejecución del mismo autor/proyecto."""

    @abstractmethod
    def get_active_for_user(self, *, project_id: UUID, user_id: str) -> AgentMessage | None:
        """Busca el mensaje running propio del proyecto."""

    @abstractmethod
    def list_for_project(self, *, project_id: UUID, limit: int, offset: int, snapshot_at: datetime) -> list[AgentMessage]:
        """Lista mensajes de la conversación por página y snapshot estable."""

    @abstractmethod
    def save_terminal(self, message: AgentMessage) -> bool:
        """Actualiza solo un mensaje running activo a un estado terminal."""

    def link_root_message(self, *, message_id: UUID, root_message_id: UUID) -> bool:
        """Asocia un mensaje a su mensaje raíz dentro del mismo hilo."""
        return False

    @abstractmethod
    def save_plan_progress(self, message: AgentMessage) -> bool:
        """Actualiza el plan de un mensaje running con control optimista de versión."""

    @abstractmethod
    def image_url_is_referenced(self, message_id: UUID, image_url: str) -> bool | None:
        """Devuelve None si no puede comprobarse una referencia persistida."""

    def find_pending_visual_clarifications(
        self, *, user_id: str, project_id: UUID
    ) -> list[AgentMessage]:
        """Busca aclaraciones terminales recientes del mismo actor y proyecto."""
        return []

    def claim_visual_clarification(
        self,
        *,
        message_id: UUID,
        expected_version: int,
        continuation_id: UUID,
        user_id: str,
        project_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        """Reclama una aclaración una sola vez; adaptadores antiguos fallan cerrado."""
        return False
