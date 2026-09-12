from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.application.ports.readers.project_member_list_reader import (
    ProjectMemberListReader,
)
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.domain.exceptions import (
    ProjectNotFoundException,
    ProjectNotOwnedException,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
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
    """Manejador de consulta para listar colaboradores de un proyecto con verificación de propiedad."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        project_member_list_reader: ProjectMemberListReader,
    ) -> None:
        self.project_repository = project_repository
        self.project_member_list_reader = project_member_list_reader

    def execute(self, query: ListProjectMembersQuery) -> ProjectMemberListDTO:
        project = self.project_repository.find_by_id(query.project_id)
        if project is None:
            raise ProjectNotFoundException()

        if not project.is_owner(query.user_id):
            raise ProjectNotOwnedException()

        items = self.project_member_list_reader.list_members(
            project_id=query.project_id,
            status=query.status,
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
