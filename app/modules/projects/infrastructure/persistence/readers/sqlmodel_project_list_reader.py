from sqlalchemy import literal
from sqlmodel import Session, select

from app.modules.projects.application.ports.readers.project_list_reader import (
    ProjectListItem,
    ProjectListReader,
)
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


class SQLModelProjectListReader(ProjectListReader):
    """Implementación en SQLModel del lector de proyectos propios y compartidos."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_projects_for_user(self, user_id: str) -> list[ProjectListItem]:
        # 1. Proyectos propios
        owned_statement = (
            select(
                ProjectModel.id,
                ProjectModel.name,
                ProjectModel.description,
                ProjectModel.thumbnail_url,
                literal(True).label("is_owner"),
            )
            .where(
                ProjectModel.owner_id == user_id,
                ProjectModel.deleted_date.is_(None),
            )
        )

        # 2. Proyectos compartidos donde el usuario es colaborador activo
        shared_statement = (
            select(
                ProjectModel.id,
                ProjectModel.name,
                ProjectModel.description,
                ProjectModel.thumbnail_url,
                literal(False).label("is_owner"),
            )
            .join(ProjectMemberModel, ProjectMemberModel.project_id == ProjectModel.id)
            .where(
                ProjectMemberModel.user_id == user_id,
                ProjectMemberModel.status == ProjectMemberStatus.ACTIVE.value,
                ProjectMemberModel.deleted_date.is_(None),
                ProjectModel.owner_id != user_id,
                ProjectModel.deleted_date.is_(None),
            )
        )

        statement = owned_statement.union_all(shared_statement)
        rows = self.db.exec(statement).all()

        return [
            ProjectListItem(
                id=row[0],
                name=row[1],
                description=row[2],
                thumbnail_url=row[3],
                is_owner=bool(row[4]),
            )
            for row in rows
        ]
