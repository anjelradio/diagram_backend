from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.exceptions import (
    DiagramAttributeIdConflictException,
    DiagramClassNotFoundException,
    InvalidAttributePositionException,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramAttributeCreatedEvent


@dataclass(frozen=True, slots=True)
class CreateDiagramAttributeCommand:
    """Comando para crear un atributo secundario en una clase."""

    id: UUID
    class_id: UUID
    user_id: str
    name: str
    position: int


class CreateDiagramAttributeUseCase:
    """Caso de uso para crear un atributo secundario con validación de posición e idempotencia."""

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

    def execute(
        self, command: CreateDiagramAttributeCommand
    ) -> tuple[DiagramAttribute, bool]:
        """Ejecuta la creación del atributo secundario.

        Retorna (DiagramAttribute, is_created).
        is_created es False en reintentos idempotentes exactos.
        """
        # 1. Resolver clase y verificar existencia
        diagram_class = self.diagram_class_repository.find_by_id(command.class_id)
        if diagram_class is None:
            raise DiagramClassNotFoundException()

        # 2. Autorización de escritura
        self.access_policy.ensure_write_access(
            diagram_class.project_id, command.user_id
        )

        clean_name = command.name.strip()

        # 3. Comprobar si el ID ya existe (idempotencia o conflicto)
        existing = self.diagram_attribute_repository.find_by_id(command.id)
        if existing is not None:
            if (
                existing.class_id == command.class_id
                and existing.name == clean_name
                and existing.position == command.position
            ):
                return existing, False
            raise DiagramAttributeIdConflictException()

        # 4. Validar rango de posición de inserción
        existing_attributes = self.diagram_attribute_repository.list_by_class_id(
            command.class_id
        )
        next_pos = len(existing_attributes)
        if command.position < 1 or command.position > next_pos:
            raise InvalidAttributePositionException()

        # 5. Si se inserta antes del final, desplazar los hermanos posteriores
        if command.position < next_pos:
            secondaries = [a for a in existing_attributes if not a.is_primary_key]
            for a in secondaries:
                if a.position >= command.position:
                    a.reposition(a.position + 1)
            self.diagram_attribute_repository.reorder_attributes(
                command.class_id, secondaries
            )

        # 6. Crear entidad de atributo secundario (tipo null, nullable por defecto)
        new_attr = DiagramAttribute.create_secondary(
            id=command.id,
            class_id=command.class_id,
            name=clean_name,
            position=command.position,
        )

        # 7. Persistir y confirmar transacción
        self.diagram_attribute_repository.save(new_attr)
        self.uow.publish_event(DiagramAttributeCreatedEvent(
            project_id=diagram_class.project_id, sender_id=command.user_id,
            data={"id": str(new_attr.id), "class_id": str(new_attr.class_id), "name": new_attr.name,
                  "data_type": new_attr.data_type.value if new_attr.data_type else None,
                  "position": new_attr.position, "is_primary_key": new_attr.is_primary_key,
                  "is_nullable": new_attr.is_nullable, "is_foreign_key": new_attr.is_foreign_key},
        ))
        self.uow.commit()

        return new_attr, True
