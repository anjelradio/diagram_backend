from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.services.diagram_audit_serializer import (
    create_diagram_audit_event,
    serialize_relation,
)
from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.exceptions import (
    DiagramRelationNotFoundException,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramRelationRenamedEvent


@dataclass(frozen=True, slots=True)
class RenameDiagramRelationCommand:
    """Comando para renombrar una relación de diagrama."""

    relation_id: UUID
    user_id: str
    name: str
    event_sender_id: str | None = None


class RenameDiagramRelationUseCase:
    """Caso de uso para renombrar una relación de diagrama."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_relation_repository: DiagramRelationRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_relation_repository = diagram_relation_repository
        self.uow = uow

    def execute(self, command: RenameDiagramRelationCommand) -> DiagramRelation:
        """Renombra la relación verificando permisos y restricción asociativa."""
        existing = self.diagram_relation_repository.find_by_id(command.relation_id)
        if existing is None:
            raise DiagramRelationNotFoundException()

        self.access_policy.ensure_write_access(existing.project_id, command.user_id)

        clean_name = command.name.strip()
        old_name = existing.name
        payload_before = serialize_relation(existing)

        existing.rename(clean_name)
        payload_after = serialize_relation(existing)

        self.diagram_relation_repository.save(existing)
        self.uow.publish_event(DiagramRelationRenamedEvent(
            project_id=existing.project_id, sender_id=command.event_sender_id or command.user_id,
            data={"relation_id": str(existing.id), "name": existing.name},
        ))
        if old_name != existing.name:
            self.uow.publish_event(
                create_diagram_audit_event(
                    project_id=existing.project_id,
                    user_id=command.user_id,
                    event_sender_id=command.event_sender_id,
                    entity_type=DiagramAuditEntityType.RELATION,
                    entity_id=existing.id,
                    entity_name=existing.name,
                    action=DiagramAuditAction.UPDATE,
                    use_case="RENAME_RELATION",
                    summary=f"Se renombró la relación de '{old_name}' a '{existing.name}'",
                    payload_before=payload_before,
                    payload_after=payload_after,
                )
            )
        self.access_policy.touch_project(existing.project_id)
        self.uow.commit()

        return existing

