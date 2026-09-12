from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.exceptions import (
    ProjectMemberNotFoundException,
    ProjectNotFoundException,
    ProjectNotOwnedException,
)
from app.modules.projects.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.domain.repositories.project_repository import ProjectRepository
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class DemoteProjectMemberCommand:
    """Comando para degradar un colaborador a rol READER."""

    project_id: UUID
    member_id: UUID
    user_id: str


class DemoteProjectMemberUseCase:
    """Caso de uso para que el propietario degrade a un colaborador a READER."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        project_member_repository: ProjectMemberRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.project_repository = project_repository
        self.project_member_repository = project_member_repository
        self.uow = uow

    def execute(self, command: DemoteProjectMemberCommand) -> None:
        project = self.project_repository.find_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundException()

        if not project.is_owner(command.user_id):
            raise ProjectNotOwnedException()

        member = self.project_member_repository.find_by_id(command.member_id)
        if member is None or member.project_id != project.id:
            raise ProjectMemberNotFoundException()

        member.demote_to_reader()
        self.project_member_repository.save(member)
        self.uow.commit()
