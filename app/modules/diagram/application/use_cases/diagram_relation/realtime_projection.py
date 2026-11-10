"""Proyección acotada de clases/atributos materializados para eventos realtime."""

from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.entities.diagram_class import DiagramClass


def class_snapshot(
    diagram_class: DiagramClass, attributes: list[DiagramAttribute]
) -> dict[str, object]:
    return {
        "id": str(diagram_class.id),
        "name": diagram_class.name,
        "position_x": diagram_class.position_x,
        "position_y": diagram_class.position_y,
        "attributes": [attribute_snapshot(item) for item in attributes],
    }


def attribute_snapshot(attribute: DiagramAttribute) -> dict[str, object]:
    return {
        "id": str(attribute.id),
        "class_id": str(attribute.class_id),
        "name": attribute.name,
        "data_type": attribute.data_type.value if attribute.data_type else None,
        "position": attribute.position,
        "is_primary_key": attribute.is_primary_key,
        "is_nullable": attribute.is_nullable,
        "is_foreign_key": attribute.is_foreign_key,
        "referenced_class_id": (
            str(attribute.referenced_class_id)
            if attribute.referenced_class_id is not None
            else None
        ),
        "relation_id": str(attribute.relation_id) if attribute.relation_id else None,
    }
