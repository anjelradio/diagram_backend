from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.diagram.application.services.diagram_relation_materializer import (
    MaterializationStrategy,
)
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)


class RelationEndpointRequest(BaseModel):
    """Extremo origen o destino de una relación."""

    model_config = ConfigDict(extra="forbid")

    class_id: UUID
    handle: DiagramRelationHandle
    cardinality: DiagramCardinality | None = None


class ForeignAttributeRequest(BaseModel):
    """Atributo de clave foránea secundario provisto en la materialización."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    class_id: UUID
    name: str = Field(min_length=1, max_length=255)
    data_type: Literal["UUID"] = "UUID"
    position: int = Field(ge=1)
    is_primary_key: Literal[False] = False
    is_nullable: bool
    is_foreign_key: Literal[True] = True
    referenced_class_id: UUID
    relation_id: UUID


class SharedPrimaryKeyRequest(BaseModel):
    """Datos para promover la PK de una subclase a clave foránea compartida."""

    model_config = ConfigDict(extra="forbid")

    attribute_id: UUID
    class_id: UUID
    referenced_class_id: UUID
    relation_id: UUID


class PrimaryAttributeRequest(BaseModel):
    """Clave primaria canónica para la clase puente."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: Literal["id"] = "id"
    data_type: Literal["UUID"] = "UUID"
    position: Literal[0] = 0
    is_primary_key: Literal[True] = True
    is_nullable: Literal[False] = False


class BridgeClassRequest(BaseModel):
    """Definición atómica de la clase puente N:M con su PK y dos FK."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str = Field(min_length=1, max_length=255)
    position_x: float
    position_y: float
    handle: DiagramRelationHandle
    primary_attribute: PrimaryAttributeRequest
    foreign_attributes: list[ForeignAttributeRequest] = Field(
        min_length=2, max_length=2
    )


class RelationMaterializationRequest(BaseModel):
    """Payload de materialización relacional atómica generada en cliente."""

    model_config = ConfigDict(extra="forbid")

    strategy: MaterializationStrategy
    foreign_attributes: list[ForeignAttributeRequest] = Field(
        default_factory=list, max_length=1
    )
    shared_primary_key: SharedPrimaryKeyRequest | None = None
    bridge_class: BridgeClassRequest | None = None


class CreateRelationRequest(BaseModel):
    """Petición compuesta para crear una relación y materializarla atómicamente."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str = Field(default="Nueva relación", max_length=255)
    relation_type: DiagramRelationType
    source: RelationEndpointRequest
    target: RelationEndpointRequest
    materialization: RelationMaterializationRequest

    @model_validator(mode="after")
    def validate_name_by_relation_type(self) -> "CreateRelationRequest":
        if self.relation_type == DiagramRelationType.ASSOCIATION:
            cleaned = self.name.strip()
            if not cleaned:
                raise ValueError("El nombre de una asociación no puede estar vacío.")
            self.name = cleaned
        else:
            if self.name and self.name.strip() != "":
                raise ValueError("Las relaciones no asociativas deben conservar el nombre vacío.")
            self.name = ""
        return self


class RenameRelationRequest(BaseModel):
    """Petición para renombrar una relación existente."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
