from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class CreateProjectCommand:
    """Comando para crear un nuevo proyecto en blanco."""

    owner_id: str


class CreateProjectUseCase:
    """Caso de uso para crear un proyecto con nombre por defecto."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.project_repository = project_repository
        self.uow = uow

    def execute(self, command: CreateProjectCommand) -> UUID:
        project = Project.create(owner_id=command.owner_id)
        self.project_repository.save(project)
        self.uow.commit()
        return project.id
