from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ProjectCreatedResponse(BaseModel):
    """Respuesta al crear un proyecto exitosamente."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Identificador único del proyecto creado")


class ProjectItemResponse(BaseModel):
    """Representación de un proyecto en el listado del usuario."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Identificador único del proyecto")
    name: str = Field(description="Nombre del proyecto")
    description: str | None = Field(default=None, description="Descripción opcional del proyecto")
    thumbnail_url: str | None = Field(default=None, description="URL opcional de miniatura del proyecto")
    is_owner: bool = Field(description="Indica si el usuario autenticado es el propietario")


class ProjectListResponse(BaseModel):
    """Listado de proyectos propios y compartidos del usuario."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ProjectItemResponse] = Field(
        default_factory=list,
        description="Lista de proyectos accesibles por el usuario",
    )


class UpdateProjectRequest(BaseModel):
    """Cuerpo de petición para actualizar parcialmente un proyecto."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Nuevo nombre para el proyecto",
    )
    description: str | None = Field(
        default=None,
        description="Nueva descripción para el proyecto",
    )
