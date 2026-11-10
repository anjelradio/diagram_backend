from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.services.diagram_audit_serializer import (
    create_diagram_audit_event,
    serialize_attribute,
    serialize_class,
    serialize_relation,
)
from app.modules.diagram.application.use_cases.diagram_relation.realtime_projection import (
    class_snapshot,
)
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort
from app.modules.diagram.domain.events.diagram_events import DiagramRelationDeletedEvent


@dataclass(frozen=True, slots=True)
class DeleteDiagramRelationCommand:
    """Comando para eliminar una relación de diagrama y sus artefactos derivados."""

    relation_id: UUID
    user_id: str
    event_sender_id: str | None = None


class DeleteDiagramRelationUseCase:
    """Caso de uso para eliminar físicamente una relación, revertir PKs/FKs y limpiar cascadas."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_relation_repository: DiagramRelationRepository,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_relation_repository = diagram_relation_repository
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.uow = uow

    def execute(
        self,
        command: DeleteDiagramRelationCommand,
        *,
        commit_transaction: bool = True,
    ) -> None:
        """Elimina físicamente la relación y revierte/elimina sus artefactos derivados."""
        relation = self.diagram_relation_repository.find_by_id(command.relation_id)
        if relation is None:
            # Reintento idempotente: si ya no existe, retorno silencioso exitoso
            return

        self.access_policy.ensure_write_access(relation.project_id, command.user_id)

        source_class = self.diagram_class_repository.find_by_id(relation.source_class_id)
        target_class = self.diagram_class_repository.find_by_id(relation.target_class_id)
        source_name = source_class.name if source_class is not None else "Clase desconocida"
        target_name = target_class.name if target_class is not None else "Clase desconocida"

        bridge_class_snapshot = None
        if relation.bridge_class_id is not None:
            bridge_class = self.diagram_class_repository.find_by_id(relation.bridge_class_id)
            if bridge_class is not None:
                bridge_attrs = self.diagram_attribute_repository.list_by_class_id(bridge_class.id)
                bridge_class_snapshot = serialize_class(bridge_class, attributes=bridge_attrs)

        raw_fk_attrs = self.diagram_attribute_repository.list_by_relation_id(relation.id)
        affected_foreign_attributes = [serialize_attribute(a) for a in raw_fk_attrs]

        payload_before = serialize_relation(
            relation,
            source_class_name=source_name,
            target_class_name=target_name,
            bridge_class_snapshot=bridge_class_snapshot,
            affected_foreign_attributes=affected_foreign_attributes,
        )

        # 1. Limpieza de atributos derivados según la estrategia de materialización
        bridge_class_id_to_delete: UUID | None = None
        affected_class_ids: set[UUID] = set()
        removed_attribute_ids: list[str] = []

        if relation.is_many_to_many or relation.bridge_class_id is not None:
            # Caso BRIDGE_CLASS: eliminar todos los atributos de la clase puente
            if relation.bridge_class_id is not None:
                bridge_class_id_to_delete = relation.bridge_class_id
                bridge_attrs = self.diagram_attribute_repository.list_by_class_id(
                    relation.bridge_class_id
                )
                for attr in bridge_attrs:
                    self.diagram_attribute_repository.delete(attr.id)
        else:
            # Caso FOREIGN_KEY (1:N, 1:1, Aggregation, Composition, Generalization, Realization, Dependency):
            # Eliminar atributos FK derivados y compactar posiciones en las clases receptoras
            fk_attrs = self.diagram_attribute_repository.list_by_relation_id(
                relation.id
            )
            affected_class_ids: set[UUID] = set()
            for attr in fk_attrs:
                if attr.is_primary_key:
                    attr.revert_shared_primary_key()
                    self.diagram_attribute_repository.save(attr)
                    affected_class_ids.add(attr.class_id)
                else:
                    self.diagram_attribute_repository.delete(attr.id)
                    affected_class_ids.add(attr.class_id)
                    removed_attribute_ids.append(str(attr.id))

            # Compactar posiciones en cada clase receptora afectada
            for class_id in affected_class_ids:
                remaining = self.diagram_attribute_repository.list_by_class_id(class_id)
                secondaries = [a for a in remaining if not a.is_primary_key]
                for idx, sec in enumerate(secondaries, start=1):
                    sec.compact_position(idx)
                self.diagram_attribute_repository.reorder_attributes(
                    class_id, secondaries
                )

        # 2. Eliminar la relación primero para que no quede referencia activa hacia la clase puente
        self.diagram_relation_repository.delete(relation.id)
        self.uow.flush()

        # 3. Eliminar la clase puente si existía
        if bridge_class_id_to_delete is not None:
            self.diagram_class_repository.delete(bridge_class_id_to_delete)
            self.uow.flush()
        materialized_classes = []
        for class_id in sorted(affected_class_ids, key=str):
            affected_class = self.diagram_class_repository.find_by_id(class_id)
            if affected_class is not None:
                materialized_classes.append(
                    class_snapshot(
                        affected_class,
                        self.diagram_attribute_repository.list_by_class_id(class_id),
                    )
                )

        self.uow.publish_event(DiagramRelationDeletedEvent(
            project_id=relation.project_id, sender_id=command.event_sender_id or command.user_id,
            data={
                "relation_id": str(relation.id),
                "materialized_classes": materialized_classes,
                "removed_class_ids": (
                    [str(bridge_class_id_to_delete)]
                    if bridge_class_id_to_delete is not None
                    else []
                ),
                "removed_attribute_ids": removed_attribute_ids,
            },
        ))
        rel_display = relation.name if relation.name else relation.relation_type.value
        self.uow.publish_event(
            create_diagram_audit_event(
                project_id=relation.project_id,
                user_id=command.user_id,
                event_sender_id=command.event_sender_id,
                entity_type=DiagramAuditEntityType.RELATION,
                entity_id=relation.id,
                entity_name=rel_display,
                action=DiagramAuditAction.DELETE,
                use_case="DELETE_RELATION",
                summary=f"Se eliminó la relación '{rel_display}' entre '{source_name}' y '{target_name}'",
                payload_before=payload_before,
                payload_after=None,
            )
        )
        if commit_transaction:
            self.access_policy.touch_project(relation.project_id)
            self.uow.commit()

