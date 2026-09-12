from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus


@dataclass(frozen=True, slots=True)
class ProjectMemberItem:
    """Elemento proyectado del listado de participantes de un proyecto."""

    id: UUID
    user_id: str
    name: str
    email: str
    image: str | None
    role: ProjectMemberRole
    status: ProjectMemberStatus


class ProjectMemberListReader(ABC):
    """Puerto de lectura para obtener colaboradores de un proyecto con su perfil de usuario."""

    @abstractmethod
    def list_members(
        self, project_id: UUID, status: ProjectMemberStatus | None = None
    ) -> list[ProjectMemberItem]:
        """Obtiene en una sola consulta los miembros de un proyecto con sus datos de usuario, filtrables por estado."""
        raise NotImplementedError
