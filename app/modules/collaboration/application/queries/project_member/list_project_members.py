from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.application.ports.readers.project_member_list_reader import (
    ProjectMemberListReader,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.exceptions import (
    ProjectNotOwnedException,
)


@dataclass(frozen=True, slots=True)
class ListProjectMembersQuery:
    """Parámetros de consulta para listar los colaboradores de un proyecto."""

    project_id: UUID
    user_id: str
    status: ProjectMemberStatus | None = None


@dataclass(frozen=True, slots=True)
class ProjectMemberDTO:
    """DTO de salida para un colaborador del proyecto."""

    id: UUID
    user_id: str
    name: str
    email: str
    image: str | None
    role: ProjectMemberRole
    status: ProjectMemberStatus


@dataclass(frozen=True, slots=True)
class ProjectMemberListDTO:
    """DTO de salida con la colección de colaboradores del proyecto."""

    items: tuple[ProjectMemberDTO, ...]


class ListProjectMembersQueryHandler:
    """Manejador de consulta para listar colaboradores con control de acceso por rol."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        project_member_list_reader: ProjectMemberListReader,
    ) -> None:
        self.access_policy = access_policy
        self.project_member_list_reader = project_member_list_reader

    def execute(self, query: ListProjectMembersQuery) -> ProjectMemberListDTO:
        context = self.access_policy.resolve_access(query.project_id, query.user_id)

        if context.access_role == ProjectAccessRole.OWNER:
            status_filter = query.status
        else:
            if query.status is not None and query.status != ProjectMemberStatus.ACTIVE:
                raise ProjectNotOwnedException()
            status_filter = ProjectMemberStatus.ACTIVE

        items = self.project_member_list_reader.list_members(
            project_id=query.project_id,
            status=status_filter,
        )

        member_dtos = tuple(
            ProjectMemberDTO(
                id=item.id,
                user_id=item.user_id,
                name=item.name,
                email=item.email,
                image=item.image,
                role=item.role,
                status=item.status,
            )
            for item in items
        )
        return ProjectMemberListDTO(items=member_dtos)
