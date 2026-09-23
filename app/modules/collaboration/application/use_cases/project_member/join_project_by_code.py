from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.domain.entities.invitation import Invitation
from app.modules.collaboration.domain.entities.project_member import ProjectMember
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.exceptions import (
    InvitationNotFoundException,
    UserBannedException,
)
from app.modules.collaboration.domain.repositories.invitation_repository import (
    InvitationRepository,
)
from app.modules.collaboration.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class JoinProjectByCodeCommand:
    """Comando para unirse a un proyecto mediante código de invitación."""

    code: str
    user_id: str


@dataclass(frozen=True, slots=True)
class JoinProjectResult:
    """Resultado de la operación de unirse a un proyecto."""

    project_id: UUID


class JoinProjectByCodeUseCase:
    """Caso de uso para unirse o reactivarse en un proyecto mediante código alfanumérico."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        invitation_repository: InvitationRepository,
        project_member_repository: ProjectMemberRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.project_repository = project_repository
        self.invitation_repository = invitation_repository
        self.project_member_repository = project_member_repository
        self.uow = uow

    def execute(self, command: JoinProjectByCodeCommand) -> JoinProjectResult:
        # 1. Validar formato sintáctico del código
        valid_code = Invitation.validate_code(command.code)

        # 2. Buscar invitación y verificar vigencia
        invitation = self.invitation_repository.find_by_code(valid_code)
        if invitation is None or invitation.is_expired():
            raise InvitationNotFoundException()

        # 3. Validar existencia y disponibilidad del proyecto
        project = self.project_repository.find_by_id(invitation.project_id)
        if project is None:
            raise ProjectNotFoundException()

        # 4. Si el usuario ya es el propietario, retornar de forma idempotente el project_id
        if project.is_owner(command.user_id):
            return JoinProjectResult(project_id=project.id)

        # 5. Gestionar participación (crear, reactivar o rechazar)
        member = self.project_member_repository.find_by_project_and_user(
            project_id=project.id,
            user_id=command.user_id,
        )

        if member is None:
            # Nuevo participante como READER
            new_member = ProjectMember.create_reader(
                project_id=project.id,
                user_id=command.user_id,
            )
            self.project_member_repository.save(new_member)
            self.uow.commit()
        else:
            if member.is_banned():
                raise UserBannedException()
            if member.is_active():
                # Usuario ya es miembro activo: retornar de forma idempotente
                return JoinProjectResult(project_id=project.id)

            # Miembro previamente REMOVED: reactivar y asegurar rol READER
            member.reactivate()
            member.change_role(ProjectMemberRole.READER)
            self.project_member_repository.save(member)
            self.uow.commit()

        return JoinProjectResult(project_id=project.id)
