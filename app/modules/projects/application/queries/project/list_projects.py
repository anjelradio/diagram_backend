from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.application.ports.readers.project_list_reader import (
    ProjectListReader,
)


@dataclass(frozen=True, slots=True)
class ListProjectsQuery:
    """Parámetros de consulta para listar los proyectos de un usuario."""

    user_id: str


@dataclass(frozen=True, slots=True)
class ProjectSummaryDTO:
    """DTO de salida para un proyecto en el listado."""

    id: UUID
    name: str
    description: str | None
    thumbnail_url: str | None
    is_owner: bool


@dataclass(frozen=True, slots=True)
class ProjectListDTO:
    """DTO de salida con la colección de proyectos del usuario."""

    items: tuple[ProjectSummaryDTO, ...]


class ListProjectsQueryHandler:
    """Manejador de consulta para listar proyectos propios y compartidos."""

    def __init__(self, project_list_reader: ProjectListReader) -> None:
        self.project_list_reader = project_list_reader

    def execute(self, query: ListProjectsQuery) -> ProjectListDTO:
        items = self.project_list_reader.list_projects_for_user(query.user_id)
        project_dtos = tuple(
            ProjectSummaryDTO(
                id=item.id,
                name=item.name,
                description=item.description,
                thumbnail_url=item.thumbnail_url,
                is_owner=item.is_owner,
            )
            for item in items
        )
        return ProjectListDTO(items=project_dtos)
