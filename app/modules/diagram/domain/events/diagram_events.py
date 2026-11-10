"""Eventos de mutación consumidos por el adaptador de colaboración."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.shared.domain.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class DiagramMutationEvent(DomainEvent):
    project_id: UUID
    sender_id: str
    operation_type: str
    data: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class DiagramClassCreatedEvent(DiagramMutationEvent):
    operation_type: str = "CREATE_CLASS"


@dataclass(frozen=True, kw_only=True)
class DiagramClassMovedEvent(DiagramMutationEvent):
    operation_type: str = "MOVE_CLASS"


@dataclass(frozen=True, kw_only=True)
class DiagramClassRenamedEvent(DiagramMutationEvent):
    operation_type: str = "RENAME_CLASS"


@dataclass(frozen=True, kw_only=True)
class DiagramClassDeletedEvent(DiagramMutationEvent):
    operation_type: str = "DELETE_CLASS"


@dataclass(frozen=True, kw_only=True)
class DiagramAttributeCreatedEvent(DiagramMutationEvent):
    operation_type: str = "CREATE_ATTRIBUTE"


@dataclass(frozen=True, kw_only=True)
class DiagramAttributeUpdatedEvent(DiagramMutationEvent):
    operation_type: str = "UPDATE_ATTRIBUTE"


@dataclass(frozen=True, kw_only=True)
class DiagramAttributeRepositionedEvent(DiagramMutationEvent):
    operation_type: str = "REPOSITION_ATTRIBUTE"


@dataclass(frozen=True, kw_only=True)
class DiagramAttributeDeletedEvent(DiagramMutationEvent):
    operation_type: str = "DELETE_ATTRIBUTE"


@dataclass(frozen=True, kw_only=True)
class DiagramRelationCreatedEvent(DiagramMutationEvent):
    operation_type: str = "CREATE_RELATION"


@dataclass(frozen=True, kw_only=True)
class DiagramRelationRenamedEvent(DiagramMutationEvent):
    operation_type: str = "RENAME_RELATION"


@dataclass(frozen=True, kw_only=True)
class DiagramRelationDeletedEvent(DiagramMutationEvent):
    operation_type: str = "DELETE_RELATION"


@dataclass(frozen=True, kw_only=True)
class DiagramAuditRecordedEvent(DomainEvent):
    """Evento emitido tras una mutación auditada para su persistencia en la bitácora."""

    project_id: UUID
    user_id: str
    actor_type: DiagramAuditActorType
    entity_type: DiagramAuditEntityType
    entity_id: UUID
    entity_name: str
    action: DiagramAuditAction
    use_case: str
    summary: str
    parent_class_id: UUID | None = None
    parent_class_name: str | None = None
    payload_before: dict[str, Any] | None = None
    payload_after: dict[str, Any] | None = None
    user_name: str | None = None

