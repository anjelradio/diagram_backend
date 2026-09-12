from uuid import UUID
from sqlmodel import Session, select

from app.modules.projects.application.ports.readers.project_member_list_reader import (
    ProjectMemberItem,
    ProjectMemberListReader,
)
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


class SQLModelProjectMemberListReader(ProjectMemberListReader):
    """Implementación en SQLModel del lector de miembros con datos de usuario."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_members(
        self, project_id: UUID, status: ProjectMemberStatus | None = None
    ) -> list[ProjectMemberItem]:
        statement = (
            select(
                ProjectMemberModel.id,
                ProjectMemberModel.user_id,
                BetterAuthUser.name,
                BetterAuthUser.email,
                BetterAuthUser.image,
                ProjectMemberModel.role,
                ProjectMemberModel.status,
            )
            .join(
                BetterAuthUser,
                BetterAuthUser.id == ProjectMemberModel.user_id,
                isouter=True,
            )
            .where(
                ProjectMemberModel.project_id == project_id,
                ProjectMemberModel.deleted_date.is_(None),
            )
        )

        if status is not None:
            statement = statement.where(ProjectMemberModel.status == status.value)

        rows = self.db.exec(statement).all()

        return [
            ProjectMemberItem(
                id=row[0],
                user_id=row[1],
                name=row[2] or "",
                email=row[3] or "",
                image=row[4],
                role=ProjectMemberRole(row[5]),
                status=ProjectMemberStatus(row[6]),
            )
            for row in rows
        ]
