from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)


class DiagramRelationMapper:
    """Mapeador bidireccional entre la entidad DiagramRelation y el modelo SQLModel."""

    @staticmethod
    def to_entity(model: DiagramRelationModel) -> DiagramRelation:
        relation_type = DiagramRelationType(model.relation_type)
        source_cardinality = (
            DiagramCardinality(model.source_cardinality)
            if model.source_cardinality is not None
            else None
        )
        target_cardinality = (
            DiagramCardinality(model.target_cardinality)
            if model.target_cardinality is not None
            else None
        )
        source_handle = DiagramRelationHandle(model.source_handle)
        target_handle = DiagramRelationHandle(model.target_handle)
        bridge_handle = (
            DiagramRelationHandle(model.bridge_handle)
            if model.bridge_handle is not None
            else None
        )

        return DiagramRelation(
            id=model.id,
            project_id=model.project_id,
            source_class_id=model.source_class_id,
            target_class_id=model.target_class_id,
            relation_type=relation_type,
            source_handle=source_handle,
            target_handle=target_handle,
            name=model.name,
            source_cardinality=source_cardinality,
            target_cardinality=target_cardinality,
            bridge_class_id=model.bridge_class_id,
            bridge_handle=bridge_handle,
        )

    @staticmethod
    def to_model(entity: DiagramRelation) -> DiagramRelationModel:
        return DiagramRelationModel(
            id=entity.id,
            project_id=entity.project_id,
            source_class_id=entity.source_class_id,
            target_class_id=entity.target_class_id,
            name=entity.name,
            relation_type=entity.relation_type.value,
            source_cardinality=(
                entity.source_cardinality.value
                if entity.source_cardinality is not None
                else None
            ),
            target_cardinality=(
                entity.target_cardinality.value
                if entity.target_cardinality is not None
                else None
            ),
            source_handle=entity.source_handle.value,
            target_handle=entity.target_handle.value,
            bridge_class_id=entity.bridge_class_id,
            bridge_handle=(
                entity.bridge_handle.value if entity.bridge_handle is not None else None
            ),
        )
