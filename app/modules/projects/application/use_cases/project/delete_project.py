from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.exceptions import (
    ProjectNotFoundException,
    ProjectNotOwnedException,
)
from app.modules.projects.domain.repositories.project_repository import ProjectRepository
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class DeleteProjectCommand:
    """Comando para eliminar lógicamente un proyecto."""

    project_id: UUID
    user_id: str


class DeleteProjectUseCase:
    """Caso de uso para que el propietario elimine lógicamente su proyecto."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.project_repository = project_repository
        self.uow = uow

    def execute(self, command: DeleteProjectCommand) -> None:
        project = self.project_repository.find_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundException()

        if not project.is_owner(command.user_id):
            raise ProjectNotOwnedException()

        self.project_repository.delete(project.id)
        self.uow.commit()

