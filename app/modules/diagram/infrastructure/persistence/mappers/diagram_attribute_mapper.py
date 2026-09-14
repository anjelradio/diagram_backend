from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)


class DiagramAttributeMapper:
    """Mapeador bidireccional entre la entidad DiagramAttribute y el modelo SQLModel."""

    @staticmethod
    def to_entity(model: DiagramAttributeModel) -> DiagramAttribute:
        data_type = (
            DiagramAttributeDataType(model.data_type)
            if model.data_type is not None
            else None
        )
        return DiagramAttribute(
            id=model.id,
            class_id=model.class_id,
            name=model.name,
            data_type=data_type,
            position=model.position,
            is_primary_key=model.is_primary_key,
            is_nullable=model.is_nullable,
            is_foreign_key=model.is_foreign_key,
            referenced_class_id=model.referenced_class_id,
            relation_id=model.relation_id,
        )

    @staticmethod
    def to_model(entity: DiagramAttribute) -> DiagramAttributeModel:
        return DiagramAttributeModel(
            id=entity.id,
            class_id=entity.class_id,
            name=entity.name,
            data_type=entity.data_type.value if entity.data_type is not None else None,
            position=entity.position,
            is_primary_key=entity.is_primary_key,
            is_nullable=entity.is_nullable,
            is_foreign_key=entity.is_foreign_key,
            referenced_class_id=entity.referenced_class_id,
            relation_id=entity.relation_id,
        )

