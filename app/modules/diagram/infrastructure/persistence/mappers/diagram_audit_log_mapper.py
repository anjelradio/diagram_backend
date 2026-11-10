from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_audit_log_model import (
    DiagramAuditLogModel,
)


class DiagramAuditLogMapper:
    """Mapeador bidireccional entre la entidad DiagramAuditLog y el modelo SQLModel."""

    @staticmethod
    def to_domain(model: DiagramAuditLogModel) -> DiagramAuditLog:
        return DiagramAuditLog(
            id=model.id,
            project_id=model.project_id,
            user_id=model.user_id,
            user_name=model.user_name,
            actor_type=DiagramAuditActorType(model.actor_type),
            entity_type=DiagramAuditEntityType(model.entity_type),
            entity_id=model.entity_id,
            entity_name=model.entity_name,
            action=DiagramAuditAction(model.action),
            use_case=model.use_case,
            summary=model.summary,
            payload_before=model.payload_before,
            payload_after=model.payload_after,
            parent_class_id=model.parent_class_id,
            parent_class_name=model.parent_class_name,
            created_date=model.created_date,
        )

    @classmethod
    def to_entity(cls, model: DiagramAuditLogModel) -> DiagramAuditLog:
        return cls.to_domain(model)

    @staticmethod
    def to_model(entity: DiagramAuditLog) -> DiagramAuditLogModel:
        return DiagramAuditLogModel(
            id=entity.id,
            project_id=entity.project_id,
            user_id=entity.user_id,
            user_name=entity.user_name,
            actor_type=entity.actor_type.value,
            entity_type=entity.entity_type.value,
            entity_id=entity.entity_id,
            entity_name=entity.entity_name,
            parent_class_id=entity.parent_class_id,
            parent_class_name=entity.parent_class_name,
            action=entity.action.value,
            use_case=entity.use_case,
            summary=entity.summary,
            payload_before=entity.payload_before,
            payload_after=entity.payload_after,
            created_date=entity.created_date,
        )
