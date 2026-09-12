from app.modules.projects.domain.entities.project import Project
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


class ProjectMapper:
    """Mapper para traducir entre Project y ProjectModel."""

    @staticmethod
    def to_domain(model: ProjectModel) -> Project:
        return Project(
            id=model.id,
            owner_id=model.owner_id,
            name=model.name,
            description=model.description,
            thumbnail_url=model.thumbnail_url,
        )

    @staticmethod
    def to_model(entity: Project) -> ProjectModel:
        return ProjectModel(
            id=entity.id,
            owner_id=entity.owner_id,
            name=entity.name,
            description=entity.description,
            thumbnail_url=entity.thumbnail_url,
            deleted_date=None,
        )

    @staticmethod
    def update_model(entity: Project, model: ProjectModel) -> None:
        model.name = entity.name
        model.description = entity.description
        model.thumbnail_url = entity.thumbnail_url

