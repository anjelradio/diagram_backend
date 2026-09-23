from app.modules.collaboration.domain.entities.project_member import ProjectMember
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)


class ProjectMemberMapper:
    """Mapper para traducir entre ProjectMember y ProjectMemberModel."""

    @staticmethod
    def to_domain(model: ProjectMemberModel) -> ProjectMember:
        return ProjectMember(
            id=model.id,
            project_id=model.project_id,
            user_id=model.user_id,
            role=ProjectMemberRole(model.role),
            status=ProjectMemberStatus(model.status),
        )

    @staticmethod
    def to_model(entity: ProjectMember) -> ProjectMemberModel:
        return ProjectMemberModel(
            id=entity.id,
            project_id=entity.project_id,
            user_id=entity.user_id,
            role=entity.role,
            status=entity.status,
        )

    @staticmethod
    def update_model(entity: ProjectMember, model: ProjectMemberModel) -> None:
        model.role = entity.role
        model.status = entity.status
