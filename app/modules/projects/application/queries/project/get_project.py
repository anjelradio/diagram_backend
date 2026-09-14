from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole


@dataclass(frozen=True, slots=True)
class GetProjectQuery:
    """Parámetros de consulta para obtener el detalle de un proyecto y el rol resuelto."""

    project_id: UUID
    user_id: str


@dataclass(frozen=True, slots=True)
class ProjectDetailDTO:
    """DTO inmutable de salida para el detalle de un proyecto."""

    id: UUID
    name: str
    description: str | None
    thumbnail_url: str | None
    access_role: ProjectAccessRole


class GetProjectQueryHandler:
    """Manejador de consulta que delega en ProjectAccessPolicy para resolver acceso y rol."""

    def __init__(self, access_policy: ProjectAccessPolicy) -> None:
        self.access_policy = access_policy

    def execute(self, query: GetProjectQuery) -> ProjectDetailDTO:
        context = self.access_policy.resolve_access(query.project_id, query.user_id)
        project = context.project
        return ProjectDetailDTO(
            id=project.id,
            name=project.name,
            description=project.description,
            thumbnail_url=project.thumbnail_url,
            access_role=context.access_role,
        )
