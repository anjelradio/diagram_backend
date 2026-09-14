from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute


class DiagramAttributeRepository(ABC):
    """Puerto de persistencia para atributos de clases de diagrama."""

    @abstractmethod
    def save(self, attribute: DiagramAttribute) -> None:
        """Guarda o actualiza un atributo."""
        ...

    @abstractmethod
    def find_by_id(self, attribute_id: UUID) -> DiagramAttribute | None:
        """Busca un atributo por su identificador único."""
        ...

    @abstractmethod
    def list_by_class_id(self, class_id: UUID) -> list[DiagramAttribute]:
        """Lista todos los atributos de una clase ordenados por posición ascendente."""
        ...

    @abstractmethod
    def find_primary_key(self, class_id: UUID) -> DiagramAttribute | None:
        """Busca el atributo de llave primaria de una clase."""
        ...

    @abstractmethod
    def get_next_position(self, class_id: UUID) -> int:
        """Calcula la siguiente posición secuencial disponible para un nuevo atributo."""
        ...

    @abstractmethod
    def reorder_attributes(
        self, class_id: UUID, ordered_attributes: list[DiagramAttribute]
    ) -> None:
        """Reordena la lista de atributos de una clase garantizando posiciones contiguas."""
        ...

    @abstractmethod
    def list_by_relation_id(self, relation_id: UUID) -> list[DiagramAttribute]:
        """Lista todos los atributos asociados a una relación dada."""
        ...

    @abstractmethod
    def list_by_referenced_class_id(
        self, referenced_class_id: UUID
    ) -> list[DiagramAttribute]:
        """Lista todos los atributos FK que referencian a una clase dada."""
        ...

    @abstractmethod
    def delete(self, attribute_id: UUID) -> None:
        """Elimina físicamente un atributo de la base de datos."""
        ...
