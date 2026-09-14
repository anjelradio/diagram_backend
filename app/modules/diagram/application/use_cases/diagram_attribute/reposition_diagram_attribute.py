from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.exceptions import (
    DiagramAttributeNotFoundException,
    DiagramClassNotFoundException,
    ForeignKeyCannotBeRepositionedException,
    InvalidAttributePositionException,
    PrimaryKeyCannotBeRepositionedException,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramAttributeRepositionedEvent


@dataclass(frozen=True, slots=True)
class RepositionDiagramAttributeCommand:
    """Comando para reposicionar un atributo secundario dentro de su clase."""

    attribute_id: UUID
    user_id: str
    target_position: int


class RepositionDiagramAttributeUseCase:
    """Caso de uso para reordenar atributos secundarios manteniendo fija la PK en posición 0."""

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

    def execute(self, command: RepositionDiagramAttributeCommand) -> None:
        # 1. Buscar atributo
        attribute = self.diagram_attribute_repository.find_by_id(command.attribute_id)
        if attribute is None:
            raise DiagramAttributeNotFoundException()

        # 2. La llave primaria y claves foráneas no pueden ser reposicionadas
        if attribute.is_primary_key:
            raise PrimaryKeyCannotBeRepositionedException()
        if attribute.is_foreign_key:
            raise ForeignKeyCannotBeRepositionedException()

        # 3. Buscar clase contenedora
        diagram_class = self.diagram_class_repository.find_by_id(attribute.class_id)
        if diagram_class is None:
            raise DiagramClassNotFoundException()

        # 4. Validar permisos de edición en el proyecto
        self.access_policy.ensure_write_access(
            diagram_class.project_id, command.user_id
        )

        # 5. Obtener todos los atributos de la clase y separar secundarios
        all_attributes = self.diagram_attribute_repository.list_by_class_id(
            diagram_class.id
        )
        secondaries = [a for a in all_attributes if not a.is_primary_key]

        # 6. Validar límites de posición de destino (1 <= target <= cantidad de secundarios)
        if command.target_position < 1 or command.target_position > len(secondaries):
            raise InvalidAttributePositionException()

        # 7. Reordenar secundarios en memoria: extraer e insertar en target_position
        secondaries = [a for a in secondaries if a.id != attribute.id]
        target_index = command.target_position - 1
        secondaries.insert(target_index, attribute)

        # 8. Reasignar posiciones contiguas 1..N
        for index, sec in enumerate(secondaries, start=1):
            sec.compact_position(index)

        # 9. Persistir usando estrategia de dos fases y confirmar transacción
        self.diagram_attribute_repository.reorder_attributes(
            diagram_class.id, secondaries
        )
        self.uow.publish_event(DiagramAttributeRepositionedEvent(
            project_id=diagram_class.project_id, sender_id=command.user_id,
            data={"class_id": str(attribute.class_id), "attribute_id": str(attribute.id), "position": attribute.position},
        ))
        self.uow.commit()
