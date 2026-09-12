from uuid import UUID
from sqlmodel import Session, select

from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.repositories.project_repository import ProjectRepository
from app.modules.projects.infrastructure.persistence.mappers.project_mapper import ProjectMapper
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


class SQLModelProjectRepository(ProjectRepository):
    """Implementación en SQLModel del repositorio de proyectos."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, project: Project) -> None:
        statement = select(ProjectModel).where(ProjectModel.id == project.id)
        record = self.db.exec(statement).first()
        if record is None:
            record = ProjectMapper.to_model(project)
            self.db.add(record)
        else:
            ProjectMapper.update_model(project, record)
            self.db.add(record)

    def find_by_id(self, project_id: UUID) -> Project | None:
        statement = select(ProjectModel).where(
            ProjectModel.id == project_id,
            ProjectModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        return ProjectMapper.to_domain(record) if record else None

    def delete(self, project_id: UUID) -> None:
        statement = select(ProjectModel).where(
            ProjectModel.id == project_id,
            ProjectModel.deleted_date.is_(None),
        )
        record = self.db.exec(statement).first()
        if record is not None:
            record.soft_delete()
            self.db.add(record)

