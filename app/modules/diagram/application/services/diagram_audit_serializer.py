from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.events.diagram_events import DiagramAuditRecordedEvent


def resolve_actor_type(event_sender_id: str | None) -> DiagramAuditActorType:
    """Clasifica ASSISTANT si fue ejecutado por el agente de IA, USER en caso contrario."""
    if event_sender_id == "assistant":
        return DiagramAuditActorType.ASSISTANT
    return DiagramAuditActorType.USER


def serialize_attribute(
    attr: DiagramAttribute, class_name: str | None = None
) -> dict[str, Any]:
    """Serializa un atributo a dict JSON estructurado para auditoría."""
    return {
        "id": str(attr.id),
        "class_id": str(attr.class_id),
        "class_name": class_name,
        "name": attr.name,
        "data_type": attr.data_type.value if attr.data_type is not None else None,
        "position": attr.position,
        "is_primary_key": attr.is_primary_key,
        "is_nullable": attr.is_nullable,
        "is_foreign_key": attr.is_foreign_key,
        "referenced_class_id": (
            str(attr.referenced_class_id) if attr.referenced_class_id is not None else None
        ),
        "relation_id": (
            str(attr.relation_id) if attr.relation_id is not None else None
        ),
    }


def serialize_class(
    diagram_class: DiagramClass,
    attributes: list[DiagramAttribute] | None = None,
    cascaded_relation_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    """Serializa una clase con sus atributos y relaciones en cascada opcionales."""
    payload: dict[str, Any] = {
        "id": str(diagram_class.id),
        "project_id": str(diagram_class.project_id),
        "name": diagram_class.name,
        "position_x": diagram_class.position_x,
        "position_y": diagram_class.position_y,
    }
    if attributes is not None:
        payload["attributes"] = [
            serialize_attribute(attr, class_name=diagram_class.name)
            for attr in sorted(attributes, key=lambda a: a.position)
        ]
    if cascaded_relation_ids is not None:
        payload["cascaded_relation_ids"] = [
            str(rel_id) for rel_id in cascaded_relation_ids
        ]
    return payload


def serialize_relation(
    relation: DiagramRelation,
    source_class_name: str | None = None,
    target_class_name: str | None = None,
    bridge_class_snapshot: dict[str, Any] | None = None,
    affected_foreign_attributes: list[dict[str, Any]] | None = None,
    materialization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serializa una relación con metadatos contextuales para auditoría."""
    relation_type_str = (
        relation.relation_type.value
        if hasattr(relation.relation_type, "value")
        else str(relation.relation_type)
    )
    source_handle_str = (
        relation.source_handle.value
        if hasattr(relation.source_handle, "value")
        else str(relation.source_handle)
    )
    target_handle_str = (
        relation.target_handle.value
        if hasattr(relation.target_handle, "value")
        else str(relation.target_handle)
    )
    source_card_str = (
        relation.source_cardinality.value
        if relation.source_cardinality is not None
        and hasattr(relation.source_cardinality, "value")
        else (str(relation.source_cardinality) if relation.source_cardinality else None)
    )
    target_card_str = (
        relation.target_cardinality.value
        if relation.target_cardinality is not None
        and hasattr(relation.target_cardinality, "value")
        else (str(relation.target_cardinality) if relation.target_cardinality else None)
    )
    bridge_handle_str = (
        relation.bridge_handle.value
        if relation.bridge_handle is not None
        and hasattr(relation.bridge_handle, "value")
        else (str(relation.bridge_handle) if relation.bridge_handle else None)
    )

    payload: dict[str, Any] = {
        "id": str(relation.id),
        "project_id": str(relation.project_id),
        "name": relation.name,
        "relation_type": relation_type_str,
        "source_class_id": str(relation.source_class_id),
        "source_class_name": source_class_name,
        "target_class_id": str(relation.target_class_id),
        "target_class_name": target_class_name,
        "source_handle": source_handle_str,
        "target_handle": target_handle_str,
        "source_cardinality": source_card_str,
        "target_cardinality": target_card_str,
        "bridge_class_id": (
            str(relation.bridge_class_id) if relation.bridge_class_id is not None else None
        ),
        "bridge_handle": bridge_handle_str,
    }
    if materialization is not None:
        payload["materialization"] = materialization
    if bridge_class_snapshot is not None:
        payload["bridge_class_snapshot"] = bridge_class_snapshot
    if affected_foreign_attributes is not None:
        payload["affected_foreign_attributes"] = affected_foreign_attributes
    return payload


def create_diagram_audit_event(
    *,
    project_id: UUID,
    user_id: str,
    event_sender_id: str | None,
    entity_type: DiagramAuditEntityType,
    entity_id: UUID,
    entity_name: str,
    action: DiagramAuditAction,
    use_case: str,
    summary: str,
    parent_class_id: UUID | None = None,
    parent_class_name: str | None = None,
    payload_before: dict[str, Any] | None = None,
    payload_after: dict[str, Any] | None = None,
    user_name: str | None = None,
) -> DiagramAuditRecordedEvent:
    """Constructor unificado para generar instancias válidas de DiagramAuditRecordedEvent."""
    actor_type = resolve_actor_type(event_sender_id)
    return DiagramAuditRecordedEvent(
        project_id=project_id,
        user_id=user_id,
        actor_type=actor_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        action=action,
        use_case=use_case,
        summary=summary,
        parent_class_id=parent_class_id,
        parent_class_name=parent_class_name,
        payload_before=payload_before,
        payload_after=payload_after,
        user_name=user_name,
    )
