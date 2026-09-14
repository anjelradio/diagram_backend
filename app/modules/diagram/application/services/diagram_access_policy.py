from uuid import UUID

from app.modules.diagram.domain.exceptions import DiagramWriteForbiddenException
from app.modules.projects.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)


class DiagramAccessPolicy:
    """Política de acceso delegada para el lienzo de un proyecto.

    Delega la resolución de acceso en ProjectAccessPolicy:
    - OWNER o EDITOR: lectura y escritura (can_edit=True).
    - READER: solo lectura (escritura lanza DiagramWriteForbiddenException).
    - Sin acceso activo (inexistente, removed, banned, outsider): ProjectNotFoundException.
    """

    def __init__(
        self,
        project_repository: ProjectRepository,
        project_member_repository: ProjectMemberRepository,
        project_access_policy: ProjectAccessPolicy | None = None,
    ) -> None:
        self.project_access_policy = project_access_policy or ProjectAccessPolicy(
            project_repository=project_repository,
            project_member_repository=project_member_repository,
        )

    def ensure_read_access(self, project_id: UUID, user_id: str) -> Project:
        """Valida que el usuario tenga acceso de lectura al proyecto."""
        ctx = self.project_access_policy.ensure_read_access(project_id, user_id)
        return ctx.project

    def ensure_write_access(self, project_id: UUID, user_id: str) -> Project:
        """Valida que el usuario tenga acceso de escritura al lienzo del proyecto."""
        ctx = self.project_access_policy.resolve_access(project_id, user_id)
        if ctx.access_role == ProjectAccessRole.READER:
            raise DiagramWriteForbiddenException()
        return ctx.project
