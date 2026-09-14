from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.exceptions import (
    ForeignKeyCannotBeDeletedException,
    PrimaryKeyCannotBeDeletedException,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramAttributeDeletedEvent


@dataclass(frozen=True, slots=True)
class DeleteDiagramAttributeCommand:
    """Comando para eliminar físicamente un atributo secundario."""

    attribute_id: UUID
    user_id: str


class DeleteDiagramAttributeUseCase:
    """Caso de uso para eliminar físicamente un atributo secundario y compactar posiciones."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        uow: SqlModelUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.uow = uow

    def execute(self, command: DeleteDiagramAttributeCommand) -> None:
        # 1. Buscar atributo
        attribute = self.diagram_attribute_repository.find_by_id(command.attribute_id)
        if attribute is None:
            # Reintento idempotente: si ya no existe, retorno silencioso exitoso
            return

        # 2. La llave primaria y las claves foráneas no pueden ser eliminadas directamente
        if attribute.is_primary_key:
            raise PrimaryKeyCannotBeDeletedException()
        if attribute.is_foreign_key:
            raise ForeignKeyCannotBeDeletedException()

        # 3. Buscar clase contenedora
        diagram_class = self.diagram_class_repository.find_by_id(attribute.class_id)
        if diagram_class is None:
            # Si la clase no existe, retorno idempotente
            return

        # 4. Validar permisos de escritura en el proyecto
        self.access_policy.ensure_write_access(
            diagram_class.project_id, command.user_id
        )

        # 5. Eliminar físicamente el atributo secundario
        self.diagram_attribute_repository.delete(attribute.id)

        # 6. Obtener atributos restantes y compactar posiciones de secundarios contiguamente a 1..N
        remaining_attributes = self.diagram_attribute_repository.list_by_class_id(
            diagram_class.id
        )
        remaining_secondaries = [
            a
            for a in remaining_attributes
            if not a.is_primary_key and a.id != attribute.id
        ]
        for index, sec in enumerate(remaining_secondaries, start=1):
            sec.compact_position(index)

        # 7. Persistir reordenamiento en dos fases y confirmar transacción
        self.diagram_attribute_repository.reorder_attributes(
            diagram_class.id, remaining_secondaries
        )
        self.uow.publish_event(DiagramAttributeDeletedEvent(
            project_id=diagram_class.project_id, sender_id=command.user_id,
            data={"class_id": str(attribute.class_id), "attribute_id": str(attribute.id)},
        ))
        self.uow.commit()
