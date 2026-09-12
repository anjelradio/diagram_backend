from uuid import UUID
from sqlmodel import Session, select

from app.modules.projects.domain.entities.project_member import ProjectMember
from app.modules.projects.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.mappers.project_member_mapper import (
    ProjectMemberMapper,
)
from app.modules.projects.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)


class SQLModelProjectMemberRepository(ProjectMemberRepository):
    """Implementación en SQLModel del repositorio de participantes."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, member: ProjectMember) -> None:
        statement = select(ProjectMemberModel).where(ProjectMemberModel.id == member.id)
        record = self.db.exec(statement).first()
        if record is None:
            record = ProjectMemberMapper.to_model(member)
            self.db.add(record)
        else:
            ProjectMemberMapper.update_model(member, record)
            self.db.add(record)

    def find_by_id(self, member_id: UUID) -> ProjectMember | None:
        statement = select(ProjectMemberModel).where(
            ProjectMemberModel.id == member_id,
            ProjectMemberModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        return ProjectMemberMapper.to_domain(record) if record else None

    def find_by_project_and_user(
        self, project_id: UUID, user_id: str
    ) -> ProjectMember | None:
        statement = select(ProjectMemberModel).where(
            ProjectMemberModel.project_id == project_id,
            ProjectMemberModel.user_id == user_id,
            ProjectMemberModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        return ProjectMemberMapper.to_domain(record) if record else None
