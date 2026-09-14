from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.exceptions import (
    DiagramClassNotFoundException,
    InvalidDiagramClassNameException,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramClassRenamedEvent


@dataclass(frozen=True, slots=True)
class RenameDiagramClassCommand:
    """Comando para renombrar una clase de diagrama."""

    class_id: UUID
    user_id: str
    name: str


class RenameDiagramClassUseCase:
    """Caso de uso para renombrar una clase de diagrama."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.uow = uow

    def execute(self, command: RenameDiagramClassCommand) -> DiagramClass:
        """Renombra la clase previa verificación de permisos.

        Lanza DiagramClassNotFoundException si la clase no existe,
        InvalidDiagramClassNameException si el nombre es vacío o inválido.
        """
        existing = self.diagram_class_repository.find_by_id(command.class_id)
        if existing is None:
            raise DiagramClassNotFoundException()

        self.access_policy.ensure_write_access(existing.project_id, command.user_id)

        clean_name = command.name.strip()
        if not clean_name or len(clean_name) > 255:
            raise InvalidDiagramClassNameException()

        # Si el nombre no cambia, es una operación idempotente sin conflicto
        if existing.name == clean_name:
            return existing

        existing.rename(clean_name)
        self.diagram_class_repository.save(existing)
        self.uow.publish_event(DiagramClassRenamedEvent(
            project_id=existing.project_id, sender_id=command.user_id,
            data={"class_id": str(existing.id), "name": existing.name},
        ))
        self.uow.commit()

        return existing
