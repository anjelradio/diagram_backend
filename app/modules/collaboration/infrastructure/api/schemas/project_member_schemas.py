from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus


class MemberItemResponse(BaseModel):
    """Representación de un colaborador del proyecto."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Identificador único de la membresía")
    user_id: str = Field(description="Identificador del usuario")
    name: str = Field(description="Nombre completo del usuario")
    email: str = Field(description="Correo electrónico del usuario")
    image: str | None = Field(default=None, description="URL de imagen de perfil del usuario")
    role: ProjectMemberRole = Field(description="Rol del colaborador (READER o EDITOR)")
    status: ProjectMemberStatus = Field(description="Estado de la participación (ACTIVE, REMOVED, BANNED)")


class MemberListResponse(BaseModel):
    """Listado de colaboradores de un proyecto."""

    model_config = ConfigDict(from_attributes=True)

    items: list[MemberItemResponse] = Field(
        default_factory=list,
        description="Lista de colaboradores del proyecto",
    )
