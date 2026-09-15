from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.assistant.domain.entities.agent_activity import AgentActivity


class AgentActivityRepository(ABC):
    """Contrato abstracto para la persistencia de actividades del asistente."""

    @abstractmethod
    def save(self, activity: AgentActivity) -> None:
        """Guarda o actualiza una actividad del asistente."""
        ...

    @abstractmethod
    def find_by_id(self, activity_id: UUID) -> AgentActivity | None:
        """Busca una actividad por su identificador único."""
        ...

    @abstractmethod
    def find_active_by_project_id(self, project_id: UUID) -> AgentActivity | None:
        """Busca una actividad en curso (IN_PROGRESS) para el proyecto indicado."""
        ...

    @abstractmethod
    def find_all_by_project_id(self, project_id: UUID) -> list[AgentActivity]:
        """Obtiene todas las actividades del proyecto ordenadas por fecha de creación descendente."""
        ...
