from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory


class AgentUserMemoryRepository(ABC):
    """Persistencia del resumen de contexto por usuario y proyecto."""

    @abstractmethod
    def find_active(self, *, user_id: str, project_id: UUID) -> AgentUserMemory | None:
        """Busca la memoria activa de la pareja usuario/proyecto."""

    @abstractmethod
    def save(self, memory: AgentUserMemory) -> None:
        """Crea o actualiza la memoria activa; el caso de uso confirma el UoW."""
