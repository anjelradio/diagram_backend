from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.modules.diagram.domain.enums.diagram_audit_action import DiagramAuditAction
from app.modules.diagram.domain.enums.diagram_audit_actor_type import DiagramAuditActorType
from app.modules.diagram.domain.enums.diagram_audit_entity_type import DiagramAuditEntityType
from app.modules.diagram.domain.exceptions import InvalidDiagramAuditLogException


class DiagramAuditLog:
    """Entidad inmutable que representa una entrada en la bitácora de auditoría del proyecto."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        user_id: str,
        user_name: str,
        actor_type: DiagramAuditActorType,
        entity_type: DiagramAuditEntityType,
        entity_id: UUID,
        entity_name: str,
        action: DiagramAuditAction,
        use_case: str,
        summary: str,
        payload_before: dict[str, Any] | None,
        payload_after: dict[str, Any] | None,
        parent_class_id: UUID | None = None,
        parent_class_name: str | None = None,
        created_date: datetime | None = None,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.user_id = user_id
        self.user_name = user_name
        self.actor_type = actor_type
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.entity_name = entity_name
        self.action = action
        self.use_case = use_case
        self.summary = summary
        self.payload_before = payload_before
        self.payload_after = payload_after
        self.parent_class_id = parent_class_id
        self.parent_class_name = parent_class_name
        self.created_date = created_date or datetime.now(timezone.utc)

    @classmethod
    def record(
        cls,
        *,
        id: UUID | None = None,
        project_id: UUID,
        user_id: str,
        user_name: str,
        actor_type: DiagramAuditActorType,
        entity_type: DiagramAuditEntityType,
        entity_id: UUID,
        entity_name: str,
        action: DiagramAuditAction,
        use_case: str,
        summary: str,
        payload_before: dict[str, Any] | None = None,
        payload_after: dict[str, Any] | None = None,
        parent_class_id: UUID | None = None,
        parent_class_name: str | None = None,
        created_date: datetime | None = None,
    ) -> DiagramAuditLog:
        """Constructor de negocio con validación estricta de invariantes de auditoría."""
        clean_user_id = user_id.strip() if isinstance(user_id, str) else ""
        if not clean_user_id:
            raise InvalidDiagramAuditLogException("El user_id no puede estar vacío.")

        clean_user_name = user_name.strip() if isinstance(user_name, str) else ""
        if not clean_user_name:
            clean_user_name = clean_user_id

        clean_entity_name = entity_name.strip() if isinstance(entity_name, str) else ""
        if not clean_entity_name:
            raise InvalidDiagramAuditLogException("El entity_name no puede estar vacío.")

        clean_use_case = use_case.strip() if isinstance(use_case, str) else ""
        if not clean_use_case:
            raise InvalidDiagramAuditLogException("El use_case no puede estar vacío.")

        clean_summary = summary.strip() if isinstance(summary, str) else ""
        if not clean_summary:
            raise InvalidDiagramAuditLogException("El summary no puede estar vacío.")

        if action == DiagramAuditAction.CREATE:
            if payload_after is None:
                raise InvalidDiagramAuditLogException("Una acción CREATE exige payload_after.")
            payload_before = None
        elif action == DiagramAuditAction.DELETE:
            if payload_before is None:
                raise InvalidDiagramAuditLogException("Una acción DELETE exige payload_before.")
            payload_after = None
        elif action == DiagramAuditAction.UPDATE:
            if payload_before is None or payload_after is None:
                raise InvalidDiagramAuditLogException("Una acción UPDATE exige payload_before y payload_after.")

        return cls(
            id=id or uuid4(),
            project_id=project_id,
            user_id=clean_user_id,
            user_name=clean_user_name,
            actor_type=actor_type,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=clean_entity_name,
            action=action,
            use_case=clean_use_case,
            summary=clean_summary,
            payload_before=payload_before,
            payload_after=payload_after,
            parent_class_id=parent_class_id,
            parent_class_name=parent_class_name.strip() if parent_class_name else None,
            created_date=created_date or datetime.now(timezone.utc),
        )
