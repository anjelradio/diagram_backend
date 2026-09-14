from uuid import UUID

from sqlmodel import Session, func, select

from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.mappers.diagram_attribute_mapper import (
    DiagramAttributeMapper,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.shared.infrastructure.db.base_model import utc_now


class SQLModelDiagramAttributeRepository(DiagramAttributeRepository):
    """Implementación de SQLModel para DiagramAttributeRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, attribute: DiagramAttribute) -> None:
        model = self.session.get(DiagramAttributeModel, attribute.id)
        if model is None:
            new_model = DiagramAttributeMapper.to_model(attribute)
            self.session.add(new_model)
        else:
            model.name = attribute.name
            model.data_type = (
                attribute.data_type.value if attribute.data_type is not None else None
            )
            model.position = attribute.position
            model.is_primary_key = attribute.is_primary_key
            model.is_nullable = attribute.is_nullable
            model.is_foreign_key = attribute.is_foreign_key
            model.referenced_class_id = attribute.referenced_class_id
            model.relation_id = attribute.relation_id
            model.modified_date = utc_now()
            self.session.add(model)

    def find_by_id(self, attribute_id: UUID) -> DiagramAttribute | None:
        model = self.session.get(DiagramAttributeModel, attribute_id)
        if model is None:
            return None
        return DiagramAttributeMapper.to_entity(model)

    def list_by_class_id(self, class_id: UUID) -> list[DiagramAttribute]:
        stmt = (
            select(DiagramAttributeModel)
            .where(DiagramAttributeModel.class_id == class_id)
            .order_by(DiagramAttributeModel.position.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramAttributeMapper.to_entity(m) for m in models]

    def find_primary_key(self, class_id: UUID) -> DiagramAttribute | None:
        stmt = select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == class_id,
            DiagramAttributeModel.is_primary_key == True,  # noqa: E712
        )
        model = self.session.exec(stmt).first()
        if model is None:
            return None
        return DiagramAttributeMapper.to_entity(model)

    def get_next_position(self, class_id: UUID) -> int:
        stmt = select(func.max(DiagramAttributeModel.position)).where(
            DiagramAttributeModel.class_id == class_id
        )
        max_pos = self.session.exec(stmt).one_or_none()
        if max_pos is None:
            return 0
        return max_pos + 1

    def reorder_attributes(
        self, class_id: UUID, ordered_attributes: list[DiagramAttribute]
    ) -> None:
        """Reordena los atributos de una clase garantizando posiciones contiguas.

        Utiliza una estrategia de dos fases con posiciones temporales positivas
        para respetar el CHECK position >= 1 y no violar la unicidad de (class_id, position).
        """
        # Fase 1: Posiciones temporales positivas para evitar colisión de unicidad
        for index, attr in enumerate(ordered_attributes):
            model = self.session.get(DiagramAttributeModel, attr.id)
            if model is not None:
                if not model.is_primary_key:
                    model.position = 10000 + index
                    model.modified_date = utc_now()
                    self.session.add(model)
        self.session.flush()

        # Fase 2: Asignación de posiciones canónicas definitivas
        for attr in ordered_attributes:
            model = self.session.get(DiagramAttributeModel, attr.id)
            if model is not None:
                model.position = attr.position
                model.modified_date = utc_now()
                self.session.add(model)
        self.session.flush()

    def list_by_relation_id(self, relation_id: UUID) -> list[DiagramAttribute]:
        stmt = (
            select(DiagramAttributeModel)
            .where(DiagramAttributeModel.relation_id == relation_id)
            .order_by(DiagramAttributeModel.position.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramAttributeMapper.to_entity(m) for m in models]

    def list_by_referenced_class_id(
        self, referenced_class_id: UUID
    ) -> list[DiagramAttribute]:
        stmt = (
            select(DiagramAttributeModel)
            .where(DiagramAttributeModel.referenced_class_id == referenced_class_id)
            .order_by(DiagramAttributeModel.position.asc())
        )
        models = self.session.exec(stmt).all()
        return [DiagramAttributeMapper.to_entity(m) for m in models]

    def delete(self, attribute_id: UUID) -> None:
        model = self.session.get(DiagramAttributeModel, attribute_id)
        if model is not None:
            self.session.delete(model)
            self.session.flush()
