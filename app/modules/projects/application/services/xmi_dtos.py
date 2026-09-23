"""DTOs internos de intercambio para la serialización y deserialización XMI de Enterprise Architect."""

from dataclasses import dataclass, field
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)


@dataclass(slots=True)
class XMIAttributeDefinition:
    """Definición de un atributo extraído de una clase UML en XMI."""

    ea_id: str
    raw_name: str
    parsed_name: str
    data_type: DiagramAttributeDataType = DiagramAttributeDataType.TEXT
    is_potential_foreign_key: bool = False
    is_nullable: bool = True


@dataclass(slots=True)
class XMIClassDefinition:
    """Definición de una clase UML extraída de XMI con sus coordenadas visuales."""

    ea_id: str
    name: str
    position_x: float = 60.0
    position_y: float = 60.0
    attributes: list[XMIAttributeDefinition] = field(default_factory=list)


@dataclass(slots=True)
class XMIRelationDefinition:
    """Definición de una relación o conector UML entre dos clases."""

    ea_id: str
    source_ea_id: str
    target_ea_id: str
    relation_type: DiagramRelationType = DiagramRelationType.ASSOCIATION
    name: str = "Nueva relación"
    source_cardinality: DiagramCardinality | None = None
    target_cardinality: DiagramCardinality | None = None
    source_handle: DiagramRelationHandle = DiagramRelationHandle.RIGHT_CENTER
    target_handle: DiagramRelationHandle = DiagramRelationHandle.LEFT_CENTER
    bridge_ea_id: str | None = None
    bridge_handle: DiagramRelationHandle = DiagramRelationHandle.TOP_CENTER

    def __post_init__(self) -> None:
        if self.relation_type != DiagramRelationType.ASSOCIATION:
            self.name = ""
            self.source_cardinality = None
            self.target_cardinality = None



@dataclass(slots=True)
class XMIProjectPackage:
    """Paquete principal que encapsula el modelo completo de clases de Enterprise Architect."""

    name: str
    classes: list[XMIClassDefinition] = field(default_factory=list)
    relations: list[XMIRelationDefinition] = field(default_factory=list)
