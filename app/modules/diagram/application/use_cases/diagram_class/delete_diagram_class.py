from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.use_cases.diagram_relation.delete_diagram_relation import (
    DeleteDiagramRelationCommand,
    DeleteDiagramRelationUseCase,
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
from app.modules.diagram.domain.events.diagram_events import DiagramClassDeletedEvent


@dataclass(frozen=True, slots=True)
class DeleteDiagramClassCommand:
    """Comando para eliminar físicamente una clase de diagrama."""

    class_id: UUID
    user_id: str
    event_sender_id: str | None = None


class DeleteDiagramClassUseCase:
    """Caso de uso para eliminar físicamente una clase con soporte idempotente y cascadas de relación."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        diagram_relation_repository: DiagramRelationRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        delete_diagram_relation_use_case: DeleteDiagramRelationUseCase,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.diagram_relation_repository = diagram_relation_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.delete_diagram_relation_use_case = delete_diagram_relation_use_case
        self.uow = uow

    def execute(self, command: DeleteDiagramClassCommand) -> None:
        """Elimina físicamente la clase si existe y el usuario tiene permisos.

        Cascada de relaciones: elimina en cascada cualquier relación donde la clase participe
        como origen, destino o clase puente, limpiando FKs asociadas y revirtiendo PKs compartidas.
        """
        existing = self.diagram_class_repository.find_by_id(command.class_id)
        if existing is None:
            # Reintento idempotente ya confirmado: la clase no existe en la base de datos
            return

        self.access_policy.ensure_write_access(existing.project_id, command.user_id)

        try:
            self._delete_associated_relations(
                existing.id, command.user_id, command.event_sender_id
            )
            self._delete_class_record(existing.id)
            self.uow.publish_event(
                DiagramClassDeletedEvent(
                    project_id=existing.project_id,
                    sender_id=command.event_sender_id or command.user_id,
                    data={"class_id": str(existing.id)},
                )
            )
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise

    def _delete_associated_relations(
        self, class_id: UUID, user_id: str, event_sender_id: str | None
    ) -> None:
        """Elimina relaciones asociadas sin confirmar la unidad de trabajo compartida."""
        relations = self.diagram_relation_repository.list_by_class_id(class_id)
        for relation in relations:
            self.delete_diagram_relation_use_case.execute(
                DeleteDiagramRelationCommand(
                    relation_id=relation.id,
                    user_id=user_id,
                    event_sender_id=event_sender_id,
                ),
                commit_transaction=False,
            )

    def _delete_class_record(self, class_id: UUID) -> None:
        """Elimina atributos y clase cuando otra cascada no la retiró ya."""
        diagram_class = self.diagram_class_repository.find_by_id(class_id)
        if diagram_class is None:
            return
        for attribute in self.diagram_attribute_repository.list_by_class_id(class_id):
            self.diagram_attribute_repository.delete(attribute.id)
        self.diagram_class_repository.delete(class_id)
