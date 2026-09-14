from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)


class DiagramClassMapper:
    """Mapeador bidireccional entre la entidad de dominio DiagramClass y el modelo SQLModel."""

    @staticmethod
    def to_entity(model: DiagramClassModel) -> DiagramClass:
        return DiagramClass(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            position_x=model.position_x,
            position_y=model.position_y,
        )

    @staticmethod
    def to_model(entity: DiagramClass) -> DiagramClassModel:
        return DiagramClassModel(
            id=entity.id,
            project_id=entity.project_id,
            name=entity.name,
            position_x=entity.position_x,
            position_y=entity.position_y,
        )
