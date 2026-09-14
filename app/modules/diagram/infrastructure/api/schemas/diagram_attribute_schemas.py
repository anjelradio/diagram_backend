from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)


class CreateDiagramAttributeRequest(BaseModel):
    """Petición para crear un nuevo atributo secundario con UUID provisto por el cliente."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(description="Identificador UUIDv4 generado por el cliente")
    name: str = Field(
        min_length=1, max_length=255, description="Nombre del atributo (no vacío)"
    )
    position: int = Field(
        ge=1, description="Posición ordinal secuencial (debe ser mayor o igual a 1)"
    )


class UpdateDiagramAttributeRequest(BaseModel):
    """Petición parcial para actualizar detalles de un atributo."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Nuevo nombre para el atributo",
    )
    data_type: DiagramAttributeDataType | None = Field(
        default=None,
        description="Tipo de datos del atributo (o null para sin asignar)",
    )
    is_nullable: bool | None = Field(
        default=None,
        description="Indica si el atributo admite valores nulos",
    )

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> "UpdateDiagramAttributeRequest":
        if not self.model_fields_set:
            raise ValueError("Debes proporcionar al menos un campo para actualizar.")
        return self


class RepositionDiagramAttributeRequest(BaseModel):
    """Petición para reposicionar un atributo secundario."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(
        ge=1, description="Nueva posición de destino (mayor o igual a 1)"
    )
