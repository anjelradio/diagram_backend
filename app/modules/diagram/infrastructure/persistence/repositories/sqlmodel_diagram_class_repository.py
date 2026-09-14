from uuid import UUID

from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.mappers.diagram_class_mapper import (
    DiagramClassMapper,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.shared.infrastructure.db.base_model import utc_now
from sqlmodel import Session, select


class SQLModelDiagramClassRepository(DiagramClassRepository):
    """Implementación de SQLModel para DiagramClassRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, diagram_class: DiagramClass) -> None:
        model = self.session.get(DiagramClassModel, diagram_class.id)
        if model is None:
            new_model = DiagramClassMapper.to_model(diagram_class)
            self.session.add(new_model)
        else:
            model.name = diagram_class.name
            model.position_x = diagram_class.position_x
            model.position_y = diagram_class.position_y
            model.modified_date = utc_now()
            self.session.add(model)

    def find_by_id(self, class_id: UUID) -> DiagramClass | None:
        model = self.session.get(DiagramClassModel, class_id)
        if model is None:
            return None
        return DiagramClassMapper.to_entity(model)

    def list_by_project_id(self, project_id: UUID) -> list[DiagramClass]:
        stmt = (
            select(DiagramClassModel)
            .where(DiagramClassModel.project_id == project_id)
            .order_by(DiagramClassModel.created_date.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramClassMapper.to_entity(m) for m in models]

    def delete(self, class_id: UUID) -> None:
        model = self.session.get(DiagramClassModel, class_id)
        if model is not None:
            self.session.delete(model)
