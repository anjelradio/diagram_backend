from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DiagramAttributeSnapshotDto:
    """DTO de lectura para un atributo dentro de una clase de diagrama."""

    id: UUID
    name: str
    data_type: str | None
    position: int
    is_primary_key: bool
    is_nullable: bool
    is_foreign_key: bool = False
    referenced_class_id: UUID | None = None
    relation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DiagramClassSnapshotDto:
    """DTO de lectura para una clase de diagrama con sus atributos anidados."""

    id: UUID
    name: str
    position_x: float
    position_y: float
    attributes: list[DiagramAttributeSnapshotDto]


@dataclass(frozen=True, slots=True)
class DiagramRelationEndpointSnapshotDto:
    """Extremo de conexión de una relación de diagrama."""

    class_id: UUID
    handle: str


@dataclass(frozen=True, slots=True)
class DiagramRelationBridgeSnapshotDto:
    """Referencia a la clase puente en una relación N:M."""

    class_id: UUID
    handle: str


@dataclass(frozen=True, slots=True)
class DiagramRelationSnapshotDto:
    """DTO de lectura para una relación UML persistida."""

    id: UUID
    name: str
    relation_type: str
    source: DiagramRelationEndpointSnapshotDto
    target: DiagramRelationEndpointSnapshotDto
    source_cardinality: str | None
    target_cardinality: str | None
    bridge: DiagramRelationBridgeSnapshotDto | None


@dataclass(frozen=True, slots=True)
class DiagramSnapshotDto:
    """DTO agregado del diagrama completo."""

    classes: list[DiagramClassSnapshotDto]
    relations: list[DiagramRelationSnapshotDto]


class DiagramSnapshotReader(ABC):
    """Puerto de lectura especializado para proyecciones agregadas de diagrama."""

    @abstractmethod
    def get_classes_with_attributes_by_project_id(
        self, project_id: UUID
    ) -> list[DiagramClassSnapshotDto]:
        """Recupera todas las clases de un proyecto con sus atributos ordenados sin N+1."""
        ...

    @abstractmethod
    def get_relations_by_project_id(
        self, project_id: UUID
    ) -> list[DiagramRelationSnapshotDto]:
        """Recupera todas las relaciones de un proyecto sin N+1."""
        ...

