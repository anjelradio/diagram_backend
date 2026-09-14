from uuid import UUID
from sqlmodel import Session, or_, select

from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
)
from app.modules.diagram.infrastructure.persistence.mappers.diagram_relation_mapper import (
    DiagramRelationMapper,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.shared.infrastructure.db.base_model import utc_now


class SQLModelDiagramRelationRepository(DiagramRelationRepository):
    """Implementación SQLModel para DiagramRelationRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, relation: DiagramRelation) -> None:
        model = self.session.get(DiagramRelationModel, relation.id)
        if model is None:
            new_model = DiagramRelationMapper.to_model(relation)
            self.session.add(new_model)
        else:
            model.name = relation.name
            model.source_handle = relation.source_handle.value
            model.target_handle = relation.target_handle.value
            if relation.bridge_handle is not None:
                model.bridge_handle = relation.bridge_handle.value
            model.modified_date = utc_now()
            self.session.add(model)

    def find_by_id(self, relation_id: UUID) -> DiagramRelation | None:
        model = self.session.get(DiagramRelationModel, relation_id)
        if model is None:
            return None
        return DiagramRelationMapper.to_entity(model)

    def list_by_project_id(self, project_id: UUID) -> list[DiagramRelation]:
        stmt = (
            select(DiagramRelationModel)
            .where(DiagramRelationModel.project_id == project_id)
            .order_by(DiagramRelationModel.created_date.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramRelationMapper.to_entity(m) for m in models]

    def list_by_class_id(self, class_id: UUID) -> list[DiagramRelation]:
        stmt = (
            select(DiagramRelationModel)
            .where(
                or_(
                    DiagramRelationModel.source_class_id == class_id,
                    DiagramRelationModel.target_class_id == class_id,
                    DiagramRelationModel.bridge_class_id == class_id,
                )
            )
            .order_by(DiagramRelationModel.created_date.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramRelationMapper.to_entity(m) for m in models]

    def find_by_bridge_class_id(self, bridge_class_id: UUID) -> DiagramRelation | None:
        stmt = select(DiagramRelationModel).where(
            DiagramRelationModel.bridge_class_id == bridge_class_id
        )
        model = self.session.exec(stmt).first()
        if model is None:
            return None
        return DiagramRelationMapper.to_entity(model)

    def find_active_generalization_by_source(
        self, project_id: UUID, source_class_id: UUID
    ) -> DiagramRelation | None:
        stmt = select(DiagramRelationModel).where(
            DiagramRelationModel.project_id == project_id,
            DiagramRelationModel.source_class_id == source_class_id,
            DiagramRelationModel.relation_type == DiagramRelationType.GENERALIZATION.value,
        )
        model = self.session.exec(stmt).first()
        if model is None:
            return None
        return DiagramRelationMapper.to_entity(model)

    def delete(self, relation_id: UUID) -> None:
        model = self.session.get(DiagramRelationModel, relation_id)
        if model is not None:
            self.session.delete(model)
