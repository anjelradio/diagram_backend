from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.diagram.domain.entities.diagram_class import DiagramClass


class DiagramClassRepository(ABC):
    """Contrato de persistencia para la entidad DiagramClass."""

    @abstractmethod
    def save(self, diagram_class: DiagramClass) -> None:
        """Guarda o actualiza una clase de diagrama."""
        pass

    @abstractmethod
    def find_by_id(self, class_id: UUID) -> DiagramClass | None:
        """Busca una clase por su identificador primario."""
        pass

    @abstractmethod
    def list_by_project_id(self, project_id: UUID) -> list[DiagramClass]:
        """Lista todas las clases pertenecientes a un proyecto ordenadas por fecha de creación."""
        pass

    @abstractmethod
    def delete(self, class_id: UUID) -> None:
        """Elimina físicamente una clase de diagrama por su identificador."""
        pass
