from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.exceptions import DiagramClassNotFoundException
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramClassMovedEvent


@dataclass(frozen=True, slots=True)
class MoveDiagramClassCommand:
    """Comando para mover una clase de diagrama a nuevas coordenadas."""

    class_id: UUID
    user_id: str
    position_x: float
    position_y: float


class MoveDiagramClassUseCase:
    """Caso de uso para actualizar la posición absoluta de una clase en el lienzo."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.uow = uow

    def execute(self, command: MoveDiagramClassCommand) -> DiagramClass:
        """Mueve la clase previa verificación de permisos de escritura.

        Lanza DiagramClassNotFoundException si la clase no existe,
        o DiagramWriteForbiddenException / ProjectNotFoundException según corresponda.
        """
        existing = self.diagram_class_repository.find_by_id(command.class_id)
        if existing is None:
            raise DiagramClassNotFoundException()

        self.access_policy.ensure_write_access(existing.project_id, command.user_id)

        existing.move(command.position_x, command.position_y)
        self.diagram_class_repository.save(existing)
        self.uow.publish_event(DiagramClassMovedEvent(
            project_id=existing.project_id, sender_id=command.user_id,
            data={"class_id": str(existing.id), "position_x": existing.position_x, "position_y": existing.position_y},
        ))
        self.uow.commit()

        return existing
