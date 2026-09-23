from typing import Protocol
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.diagram.domain.exceptions import (
    DiagramAgentLockedException,
    DiagramWriteForbiddenException,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)


class ActiveAgentActivityReader(Protocol):
    """Puerto mínimo para consultar una actividad activa sin acoplar el dominio."""

    def find_active_by_project_id(self, project_id: UUID) -> object | None:
        ...


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
        active_activity_reader: ActiveAgentActivityReader | None = None,
        bypass_agent_lock: bool = False,
    ) -> None:
        self.project_access_policy = project_access_policy or ProjectAccessPolicy(
            project_repository=project_repository,
            project_member_repository=project_member_repository,
        )
        if active_activity_reader is None:
            # Las implementaciones SQLModel exponen la sesión mediante ``db``.
            # La importación perezosa mantiene el puerto opcional para pruebas y
            # evita que el dominio de diagramas dependa del adaptador de IA al cargar.
            db = getattr(project_member_repository, "db", None)
            if db is not None:
                from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
                    SQLModelAgentActivityRepository,
                )

                active_activity_reader = SQLModelAgentActivityRepository(db)
        self.active_activity_reader = active_activity_reader
        self.bypass_agent_lock = bypass_agent_lock

    def for_agent(self) -> "DiagramAccessPolicy":
        """Devuelve una política equivalente cuyo bypass solo aplica al ejecutor interno."""
        return DiagramAccessPolicy(
            project_repository=self.project_access_policy.project_repository,
            project_member_repository=self.project_access_policy.project_member_repository,
            project_access_policy=self.project_access_policy,
            active_activity_reader=self.active_activity_reader,
            bypass_agent_lock=True,
        )

    def ensure_read_access(self, project_id: UUID, user_id: str) -> Project:
        """Valida que el usuario tenga acceso de lectura al proyecto."""
        ctx = self.project_access_policy.ensure_read_access(project_id, user_id)
        return ctx.project

    def ensure_write_access(
        self,
        project_id: UUID,
        user_id: str,
        *,
        ignore_agent_lock: bool = False,
    ) -> Project:
        """Valida que el usuario tenga acceso de escritura al lienzo del proyecto."""
        ctx = self.project_access_policy.resolve_access(project_id, user_id)
        if ctx.access_role == ProjectAccessRole.READER:
            raise DiagramWriteForbiddenException()
        if (
            not self.bypass_agent_lock
            and not ignore_agent_lock
            and self.active_activity_reader is not None
            and self.active_activity_reader.find_active_by_project_id(project_id)
            is not None
        ):
            raise DiagramAgentLockedException()
        return ctx.project
