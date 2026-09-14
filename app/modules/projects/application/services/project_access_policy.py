from dataclasses import dataclass
from uuid import UUID

from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)


@dataclass(frozen=True)
class ProjectAccessContext:
    """Contexto inmutable de acceso resuelto para un usuario en un proyecto."""

    project: Project
    access_role: ProjectAccessRole


class ProjectAccessPolicy:
    """Política centralizada de acceso a proyectos.

    Reglas:
    - Precedencia de propietario: si project.owner_id == user_id, el rol es OWNER.
    - Colaboradores: si existe membresía con status ACTIVE:
        - Si role == EDITOR -> EDITOR.
        - Si role == READER -> READER.
    - Acceso no autorizado o fallo cerrado: si el proyecto no existe, está eliminado,
      la membresía no existe o tiene status REMOVED o BANNED, se lanza
      ProjectNotFoundException (404 uniforme que no revela la existencia del recurso).
    """

    def __init__(
        self,
        project_repository: ProjectRepository,
        project_member_repository: ProjectMemberRepository,
    ) -> None:
        self.project_repository = project_repository
        self.project_member_repository = project_member_repository

    def resolve_access(self, project_id: UUID, user_id: str) -> ProjectAccessContext:
        """Resuelve el acceso y rol efectivo del usuario en el proyecto.

        Lanza ProjectNotFoundException si no existe o el usuario carece de acceso activo.
        """
        project = self.project_repository.find_by_id(project_id)
        if project is None:
            raise ProjectNotFoundException()

        # 1. Precedencia de propietario
        if project.is_owner(user_id):
            return ProjectAccessContext(
                project=project,
                access_role=ProjectAccessRole.OWNER,
            )

        # 2. Membresía activa
        member = self.project_member_repository.find_by_project_and_user(
            project_id=project.id,
            user_id=user_id,
        )
        if member is None or not member.is_active():
            raise ProjectNotFoundException()

        if member.role == ProjectMemberRole.EDITOR:
            return ProjectAccessContext(
                project=project,
                access_role=ProjectAccessRole.EDITOR,
            )

        if member.role == ProjectMemberRole.READER:
            return ProjectAccessContext(
                project=project,
                access_role=ProjectAccessRole.READER,
            )

        # Cualquier otro estado o rol no reconocido falla cerrado
        raise ProjectNotFoundException()

    def ensure_read_access(self, project_id: UUID, user_id: str) -> ProjectAccessContext:
        """Valida que el usuario tenga acceso de lectura (OWNER, EDITOR o READER)."""
        return self.resolve_access(project_id, user_id)
