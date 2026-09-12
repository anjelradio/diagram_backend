from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.exceptions import (
    ProjectNotFoundException,
    ProjectNotOwnedException,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class UpdateProjectCommand:
    """Comando para actualizar información del proyecto."""

    project_id: UUID
    user_id: str
    name: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None


class UpdateProjectUseCase:
    """Caso de uso para que el propietario actualice datos de un proyecto."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.project_repository = project_repository
        self.uow = uow

    def execute(self, command: UpdateProjectCommand) -> None:
        project = self.project_repository.find_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundException()

        if not project.is_owner(command.user_id):
            raise ProjectNotOwnedException()

        project.update_info(
            name=command.name,
            description=command.description,
            thumbnail_url=command.thumbnail_url,
        )

        self.project_repository.save(project)
        self.uow.commit()
