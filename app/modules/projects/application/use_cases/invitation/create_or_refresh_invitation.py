import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.modules.projects.domain.entities.invitation import Invitation
from app.modules.projects.domain.exceptions import (
    ProjectNotFoundException,
    ProjectNotOwnedException,
)
from app.modules.projects.domain.repositories.invitation_repository import (
    InvitationRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


@dataclass(frozen=True, slots=True)
class CreateOrRefreshInvitationCommand:
    """Comando para obtener o renovar una invitación a un proyecto."""

    project_id: UUID
    user_id: str


@dataclass(frozen=True, slots=True)
class InvitationDTO:
    """DTO de salida para los datos de invitación generada o reutilizada."""

    code: str
    expires_at: datetime


class CreateOrRefreshInvitationUseCase:
    """Caso de uso para generar o renovar la invitación de un proyecto por su propietario."""

    ALPHABET = string.ascii_letters + string.digits

    def __init__(
        self,
        project_repository: ProjectRepository,
        invitation_repository: InvitationRepository,
        uow: SqlModelUnitOfWork,
        expiration_days: int = 3,
    ) -> None:
        self.project_repository = project_repository
        self.invitation_repository = invitation_repository
        self.uow = uow
        self.expiration_days = max(expiration_days, 1)

    def execute(self, command: CreateOrRefreshInvitationCommand) -> InvitationDTO:
        project = self.project_repository.find_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundException()

        if not project.is_owner(command.user_id):
            raise ProjectNotOwnedException()

        existing = self.invitation_repository.find_by_project_id(project.id)
        now = datetime.now(timezone.utc)

        # Si ya existe y está vigente, devolverla sin alterarla
        if existing is not None and not existing.is_expired(now):
            return InvitationDTO(code=existing.code, expires_at=existing.expires_at)

        # Generar código único de 10 caracteres alfanuméricos
        code = self._generate_unique_code()
        expires_at = now + timedelta(days=self.expiration_days)

        if existing is not None:
            existing.renew(code=code, expires_at=expires_at)
            self.invitation_repository.save(existing)
        else:
            invitation = Invitation.create(
                project_id=project.id,
                code=code,
                expires_at=expires_at,
            )
            self.invitation_repository.save(invitation)

        self.uow.commit()
        return InvitationDTO(code=code, expires_at=expires_at)

    def _generate_unique_code(self) -> str:
        for _ in range(20):
            code = "".join(secrets.choice(self.ALPHABET) for _ in range(Invitation.CODE_LENGTH))
            if self.invitation_repository.find_by_code(code) is None:
                return code
        raise RuntimeError("No fue posible generar un código de invitación único.")
