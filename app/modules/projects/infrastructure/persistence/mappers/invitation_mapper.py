from app.modules.projects.domain.entities.invitation import Invitation
from app.modules.projects.infrastructure.persistence.models.invitation_model import InvitationModel


class InvitationMapper:
    """Mapper para traducir entre Invitation e InvitationModel."""

    @staticmethod
    def to_domain(model: InvitationModel) -> Invitation:
        return Invitation(
            id=model.id,
            project_id=model.project_id,
            code=model.code,
            expires_at=model.expires_at,
        )

    @staticmethod
    def to_model(entity: Invitation) -> InvitationModel:
        return InvitationModel(
            id=entity.id,
            project_id=entity.project_id,
            code=entity.code,
            expires_at=entity.expires_at,
        )

    @staticmethod
    def update_model(entity: Invitation, model: InvitationModel) -> None:
        model.code = entity.code
        model.expires_at = entity.expires_at
