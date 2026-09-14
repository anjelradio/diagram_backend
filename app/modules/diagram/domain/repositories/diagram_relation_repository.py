from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation


class DiagramRelationRepository(ABC):
    """Puerto de persistencia para relaciones de diagrama."""

    @abstractmethod
    def save(self, relation: DiagramRelation) -> None:
        """Guarda o actualiza una relación de diagrama."""
        ...

    @abstractmethod
    def find_by_id(self, relation_id: UUID) -> DiagramRelation | None:
        """Busca una relación por su identificador único."""
        ...

    @abstractmethod
    def list_by_project_id(self, project_id: UUID) -> list[DiagramRelation]:
        """Lista todas las relaciones de un proyecto."""
        ...

    @abstractmethod
    def list_by_class_id(self, class_id: UUID) -> list[DiagramRelation]:
        """Lista todas las relaciones donde la clase participa como origen, destino o puente."""
        ...

    @abstractmethod
    def find_by_bridge_class_id(self, bridge_class_id: UUID) -> DiagramRelation | None:
        """Busca la relación propietaria de una clase puente dada."""
        ...

    @abstractmethod
    def find_active_generalization_by_source(
        self, project_id: UUID, source_class_id: UUID
    ) -> DiagramRelation | None:
        """Busca si la subclase ya participa como origen de una generalización en el proyecto."""
        ...

    @abstractmethod
    def delete(self, relation_id: UUID) -> None:
        """Elimina una relación de diagrama por su identificador."""
        ...
