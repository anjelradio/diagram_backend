from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
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
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramRelationDeletedEvent


@dataclass(frozen=True, slots=True)
class DeleteDiagramRelationCommand:
    """Comando para eliminar una relación de diagrama y sus artefactos derivados."""

    relation_id: UUID
    user_id: str


class DeleteDiagramRelationUseCase:
    """Caso de uso para eliminar físicamente una relación, revertir PKs/FKs y limpiar cascadas."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_relation_repository: DiagramRelationRepository,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_relation_repository = diagram_relation_repository
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.uow = uow

    def execute(self, command: DeleteDiagramRelationCommand) -> None:
        """Elimina físicamente la relación y revierte/elimina sus artefactos derivados."""
        relation = self.diagram_relation_repository.find_by_id(command.relation_id)
        if relation is None:
            # Reintento idempotente: si ya no existe, retorno silencioso exitoso
            return

        self.access_policy.ensure_write_access(relation.project_id, command.user_id)

        # 1. Limpieza de atributos derivados según la estrategia de materialización
        bridge_class_id_to_delete: UUID | None = None

        if relation.is_many_to_many or relation.bridge_class_id is not None:
            # Caso BRIDGE_CLASS: eliminar todos los atributos de la clase puente
            if relation.bridge_class_id is not None:
                bridge_class_id_to_delete = relation.bridge_class_id
                bridge_attrs = self.diagram_attribute_repository.list_by_class_id(
                    relation.bridge_class_id
                )
                for attr in bridge_attrs:
                    self.diagram_attribute_repository.delete(attr.id)
        elif relation.relation_type == DiagramRelationType.GENERALIZATION:
            # Caso SHARED_PRIMARY_KEY: revertir la PK de la subclase a PK regular
            related_attrs = self.diagram_attribute_repository.list_by_relation_id(
                relation.id
            )
            for attr in related_attrs:
                if attr.is_primary_key:
                    attr.revert_shared_primary_key()
                    self.diagram_attribute_repository.save(attr)
                else:
                    self.diagram_attribute_repository.delete(attr.id)
        else:
            # Caso FOREIGN_KEY (1:N, 1:1, Aggregation, Composition, Realization, Dependency):
            # Eliminar atributos FK derivados y compactar posiciones en las clases receptoras
            fk_attrs = self.diagram_attribute_repository.list_by_relation_id(
                relation.id
            )
            affected_class_ids: set[UUID] = set()
            for attr in fk_attrs:
                self.diagram_attribute_repository.delete(attr.id)
                affected_class_ids.add(attr.class_id)

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

        # 3. Eliminar la clase puente si existía
        if bridge_class_id_to_delete is not None:
            self.diagram_class_repository.delete(bridge_class_id_to_delete)

        self.uow.publish_event(DiagramRelationDeletedEvent(
            project_id=relation.project_id, sender_id=command.user_id,
            data={"relation_id": str(relation.id)},
        ))
        self.uow.commit()
