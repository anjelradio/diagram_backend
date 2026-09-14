import uuid
from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.exceptions import (
    DiagramClassIdConflictException,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramClassCreatedEvent


@dataclass(frozen=True, slots=True)
class CreateDiagramClassCommand:
    """Comando para crear una nueva clase de diagrama con UUID y PK provistos por el cliente."""

    id: UUID
    project_id: UUID
    user_id: str
    name: str
    position_x: float
    position_y: float
    primary_attribute_id: UUID
    primary_attribute_name: str = "id"


class CreateDiagramClassUseCase:
    """Caso de uso para crear clases de diagrama con soporte de idempotencia por UUID."""

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
        self, command: CreateDiagramClassCommand
    ) -> tuple[DiagramClass, list[DiagramAttribute], bool]:
        """Ejecuta la creación de la clase y su clave primaria atómicamente.

        Retorna (DiagramClass, list[DiagramAttribute], is_created).
        is_created es False en reintentos idempotentes exactos.
        """
        # 1. Autorización de escritura
        self.access_policy.ensure_write_access(command.project_id, command.user_id)

        clean_name = command.name.strip()

        # 2. Comprobar si el ID ya existe (idempotencia o conflicto)
        existing = self.diagram_class_repository.find_by_id(command.id)
        if existing is not None:
            # Si coincide en proyecto, nombre, coordenadas y PK id, es un reintento idempotente exitoso
            if (
                existing.project_id == command.project_id
                and existing.name == clean_name
                and existing.position_x == float(command.position_x)
                and existing.position_y == float(command.position_y)
            ):
                existing_attributes = (
                    self.diagram_attribute_repository.list_by_class_id(existing.id)
                )
                existing_pk = next(
                    (a for a in existing_attributes if a.is_primary_key), None
                )
                if (
                    existing_pk is not None
                    and existing_pk.id == command.primary_attribute_id
                ):
                    return existing, existing_attributes, False
            # De lo contrario, se está reutilizando el UUID con datos diferentes
            raise DiagramClassIdConflictException()

        # 3. Crear entidad de clase
        diagram_class = DiagramClass.create(
            id=command.id,
            project_id=command.project_id,
            name=clean_name,
            position_x=command.position_x,
            position_y=command.position_y,
        )

        # 4. Crear clave primaria provista por el cliente
        pk = DiagramAttribute.create_primary_key(
            id=command.primary_attribute_id,
            class_id=diagram_class.id,
            name=command.primary_attribute_name,
        )

        # 5. Persistir ambas entidades en una sola transacción atómica
        self.diagram_class_repository.save(diagram_class)
        self.diagram_attribute_repository.save(pk)
        self.uow.publish_event(DiagramClassCreatedEvent(
            project_id=command.project_id,
            sender_id=command.user_id,
            data={
                "id": str(diagram_class.id), "name": diagram_class.name,
                "position_x": diagram_class.position_x, "position_y": diagram_class.position_y,
                "attributes": [{"id": str(pk.id), "class_id": str(pk.class_id), "name": pk.name,
                                "data_type": pk.data_type.value if pk.data_type else None,
                                "position": pk.position, "is_primary_key": pk.is_primary_key,
                                "is_nullable": pk.is_nullable, "is_foreign_key": pk.is_foreign_key}],
            },
        ))
        self.uow.commit()

        return diagram_class, [pk], True
