from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.repositories.diagram_audit_log_repository import (
    DiagramAuditLogRepository,
)
from app.modules.diagram.infrastructure.persistence.mappers.diagram_audit_log_mapper import (
    DiagramAuditLogMapper,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_audit_log_model import (
    DiagramAuditLogModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


class SQLModelDiagramAuditLogRepository(DiagramAuditLogRepository):
    """Implementación de SQLModel para DiagramAuditLogRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, audit_log: DiagramAuditLog) -> None:
        model = self.session.get(DiagramAuditLogModel, audit_log.id)
        if model is None:
            new_model = DiagramAuditLogMapper.to_model(audit_log)
            # Intentar enriquecer user_name si viene vacío o igual al ID
            if not new_model.user_name or new_model.user_name == new_model.user_id:
                try:
                    with self.session.begin_nested():
                        row = self.session.exec(
                            select(BetterAuthUser.name).where(BetterAuthUser.id == new_model.user_id)
                        ).first()
                        if row:
                            new_model.user_name = row
                except Exception:
                    pass
            self.session.add(new_model)
        else:
            model.user_name = audit_log.user_name
            model.actor_type = audit_log.actor_type.value
            model.entity_name = audit_log.entity_name
            model.summary = audit_log.summary
            model.payload_before = audit_log.payload_before
            model.payload_after = audit_log.payload_after
            self.session.add(model)

    def find_by_id(self, audit_log_id: UUID) -> DiagramAuditLog | None:
        model = self.session.get(DiagramAuditLogModel, audit_log_id)
        if model is None:
            return None
        return DiagramAuditLogMapper.to_domain(model)

    def list_by_project(
        self,
        project_id: UUID,
        *,
        user_id: str | None = None,
        user_search: str | None = None,
        actor_type: DiagramAuditActorType | None = None,
        entity_type: DiagramAuditEntityType | None = None,
        entity_id: UUID | None = None,
        parent_class_id: UUID | None = None,
        action: DiagramAuditAction | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiagramAuditLog]:
        stmt = select(DiagramAuditLogModel).where(
            DiagramAuditLogModel.project_id == project_id
        )

        if user_id:
            stmt = stmt.where(DiagramAuditLogModel.user_id == user_id)
        if user_search:
            clean_search = user_search.strip()
            if clean_search:
                stmt = stmt.where(
                    DiagramAuditLogModel.user_name.ilike(f"%{clean_search}%")
                )
        if actor_type:
            val = actor_type.value if hasattr(actor_type, "value") else str(actor_type)
            stmt = stmt.where(DiagramAuditLogModel.actor_type == val)
        if entity_type:
            val = entity_type.value if hasattr(entity_type, "value") else str(entity_type)
            stmt = stmt.where(DiagramAuditLogModel.entity_type == val)
        if entity_id:
            stmt = stmt.where(DiagramAuditLogModel.entity_id == entity_id)
        if parent_class_id:
            stmt = stmt.where(DiagramAuditLogModel.parent_class_id == parent_class_id)
        if action:
            val = action.value if hasattr(action, "value") else str(action)
            stmt = stmt.where(DiagramAuditLogModel.action == val)

        if since:
            stmt = stmt.where(DiagramAuditLogModel.created_date >= since)
        if until:
            stmt = stmt.where(DiagramAuditLogModel.created_date <= until)

        stmt = (
            stmt.order_by(DiagramAuditLogModel.created_date.desc())
            .offset(offset)
            .limit(limit)
        )

        models = self.session.exec(stmt).all()
        return [DiagramAuditLogMapper.to_domain(m) for m in models]
