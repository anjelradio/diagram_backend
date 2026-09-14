from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class DiagramAttributeRead(BaseModel):
    """Representación de lectura de un atributo de diagrama."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    data_type: str | None = None
    position: int
    is_primary_key: bool
    is_nullable: bool
    is_foreign_key: bool = False
    referenced_class_id: UUID | None = None
    relation_id: UUID | None = None


class DiagramClassRead(BaseModel):
    """Representación de lectura de una clase de diagrama con atributos anidados."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    position_x: float
    position_y: float
    attributes: list[DiagramAttributeRead] = Field(default_factory=list)


class DiagramRelationEndpointRead(BaseModel):
    """Representación de lectura de un extremo de relación."""

    model_config = ConfigDict(from_attributes=True)

    class_id: UUID
    handle: str


class DiagramRelationBridgeRead(BaseModel):
    """Representación de lectura de la referencia a clase puente."""

    model_config = ConfigDict(from_attributes=True)

    class_id: UUID
    handle: str


class DiagramRelationRead(BaseModel):
    """Representación de lectura de una relación en el snapshot del diagrama."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    relation_type: str
    source: DiagramRelationEndpointRead
    target: DiagramRelationEndpointRead
    source_cardinality: str | None = None
    target_cardinality: str | None = None
    bridge: DiagramRelationBridgeRead | None = None


class DiagramRead(BaseModel):
    """Snapshot completo de lectura del diagrama con clases y relaciones."""

    model_config = ConfigDict(from_attributes=True)

    classes: list[DiagramClassRead]
    relations: list[DiagramRelationRead] = Field(default_factory=list)



from typing import Literal


class PrimaryAttributeRequest(BaseModel):
    """Especificación de la llave primaria obligatoria y canónica de una clase."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(description="Identificador UUIDv4 de la llave primaria generado por el cliente")
    name: Literal["id"] = Field(default="id", description="Nombre fijado en 'id'")
    data_type: Literal["UUID"] = Field(default="UUID", description="Tipo de dato fijado en 'UUID'")
    position: Literal[0] = Field(default=0, description="Posición ordinal fijada en 0")
    is_primary_key: Literal[True] = Field(default=True, description="Debe ser True")
    is_nullable: Literal[False] = Field(default=False, description="Debe ser False")


class CreateDiagramClassRequest(BaseModel):
    """Petición para crear una nueva clase con UUIDv4 y llave primaria originados en el cliente."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(description="Identificador UUIDv4 generado por el cliente")
    name: str = Field(
        min_length=1, max_length=255, description="Nombre de la clase (no vacío)"
    )
    position_x: float = Field(description="Coordenada X en el lienzo")
    position_y: float = Field(description="Coordenada Y en el lienzo")
    primary_attribute: PrimaryAttributeRequest = Field(
        description="Llave primaria generada por el cliente"
    )


class RenameDiagramClassRequest(BaseModel):
    """Petición para renombrar una clase existente."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Nuevo nombre para la clase (no vacío)",
    )


class MoveDiagramClassRequest(BaseModel):
    """Petición para actualizar las coordenadas de una clase."""

    model_config = ConfigDict(extra="forbid")

    position_x: float = Field(description="Nueva coordenada X en el lienzo")
    position_y: float = Field(description="Nueva coordenada Y en el lienzo")
