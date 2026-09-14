from uuid import UUID
from sqlmodel import Session, select

from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationBridgeSnapshotDto,
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
    DiagramSnapshotReader,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)


class SQLModelDiagramSnapshotReader(DiagramSnapshotReader):
    """Implementación de DiagramSnapshotReader en SQLModel con consultas constantes anti-N+1."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_classes_with_attributes_by_project_id(
        self, project_id: UUID
    ) -> list[DiagramClassSnapshotDto]:
        stmt = (
            select(DiagramClassModel, DiagramAttributeModel)
            .outerjoin(
                DiagramAttributeModel,
                DiagramAttributeModel.class_id == DiagramClassModel.id,
            )
            .where(DiagramClassModel.project_id == project_id)
            .order_by(
                DiagramClassModel.created_date.asc(),
                DiagramAttributeModel.position.asc(),
            )
        )
        rows = self.session.exec(stmt).all()

        classes_dict: dict[UUID, tuple[DiagramClassModel, list[DiagramAttributeSnapshotDto]]] = {}
        for class_model, attr_model in rows:
            if class_model.id not in classes_dict:
                classes_dict[class_model.id] = (class_model, [])

            if attr_model is not None:
                classes_dict[class_model.id][1].append(
                    DiagramAttributeSnapshotDto(
                        id=attr_model.id,
                        name=attr_model.name,
                        data_type=attr_model.data_type,
                        position=attr_model.position,
                        is_primary_key=attr_model.is_primary_key,
                        is_nullable=attr_model.is_nullable,
                        is_foreign_key=attr_model.is_foreign_key,
                        referenced_class_id=attr_model.referenced_class_id,
                        relation_id=attr_model.relation_id,
                    )
                )

        return [
            DiagramClassSnapshotDto(
                id=c.id,
                name=c.name,
                position_x=c.position_x,
                position_y=c.position_y,
                attributes=attrs,
            )
            for c, attrs in classes_dict.values()
        ]

    def get_relations_by_project_id(
        self, project_id: UUID
    ) -> list[DiagramRelationSnapshotDto]:
        stmt = (
            select(DiagramRelationModel)
            .where(DiagramRelationModel.project_id == project_id)
            .order_by(DiagramRelationModel.created_date.asc())
        )
        rows = self.session.exec(stmt).all()

        return [
            DiagramRelationSnapshotDto(
                id=r.id,
                name=r.name,
                relation_type=r.relation_type,
                source=DiagramRelationEndpointSnapshotDto(
                    class_id=r.source_class_id,
                    handle=r.source_handle,
                ),
                target=DiagramRelationEndpointSnapshotDto(
                    class_id=r.target_class_id,
                    handle=r.target_handle,
                ),
                source_cardinality=r.source_cardinality,
                target_cardinality=r.target_cardinality,
                bridge=DiagramRelationBridgeSnapshotDto(
                    class_id=r.bridge_class_id,
                    handle=r.bridge_handle,
                )
                if r.bridge_class_id and r.bridge_handle
                else None,
            )
            for r in rows
        ]

