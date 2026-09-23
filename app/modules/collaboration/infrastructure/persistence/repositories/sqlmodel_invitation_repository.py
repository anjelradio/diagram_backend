from uuid import UUID
from sqlmodel import Session, select

from app.modules.collaboration.domain.entities.invitation import Invitation
from app.modules.collaboration.domain.repositories.invitation_repository import (
    InvitationRepository,
)
from app.modules.collaboration.infrastructure.persistence.mappers.invitation_mapper import (
    InvitationMapper,
)
from app.modules.collaboration.infrastructure.persistence.models.invitation_model import (
    InvitationModel,
)


class SQLModelInvitationRepository(InvitationRepository):
    """Implementación en SQLModel del repositorio de invitaciones."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, invitation: Invitation) -> None:
        statement = select(InvitationModel).where(InvitationModel.id == invitation.id)
        record = self.db.exec(statement).first()
        if record is None:
            record = InvitationMapper.to_model(invitation)
            self.db.add(record)
        else:
            InvitationMapper.update_model(invitation, record)
            self.db.add(record)

    def find_by_project_id(self, project_id: UUID) -> Invitation | None:
        statement = select(InvitationModel).where(
            InvitationModel.project_id == project_id,
            InvitationModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        return InvitationMapper.to_domain(record) if record else None

    def find_by_code(self, code: str) -> Invitation | None:
        statement = select(InvitationModel).where(
            InvitationModel.code == code,
            InvitationModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        return InvitationMapper.to_domain(record) if record else None
