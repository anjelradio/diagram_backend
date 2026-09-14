from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.entities.diagram_attribute import UNSET, DiagramAttribute
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.exceptions import (
    DiagramAttributeNotFoundException,
    DiagramClassNotFoundException,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.diagram.domain.events.diagram_events import DiagramAttributeUpdatedEvent


@dataclass(frozen=True, slots=True)
class UpdateDiagramAttributeCommand:
    """Comando para actualizar detalles editables de un atributo."""

    attribute_id: UUID
    user_id: str
    name: str | object = UNSET
    data_type: DiagramAttributeDataType | None | object = UNSET
    is_nullable: bool | object = UNSET


class UpdateDiagramAttributeUseCase:
    """Caso de uso para actualizar parcialmente los detalles de un atributo protegiendo la PK."""

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

    def execute(self, command: UpdateDiagramAttributeCommand) -> DiagramAttribute:
        # 1. Buscar atributo y clase contenedora
        attribute = self.diagram_attribute_repository.find_by_id(command.attribute_id)
        if attribute is None:
            raise DiagramAttributeNotFoundException()

        diagram_class = self.diagram_class_repository.find_by_id(attribute.class_id)
        if diagram_class is None:
            raise DiagramClassNotFoundException()

        # 2. Autorización de escritura sobre el proyecto
        self.access_policy.ensure_write_access(
            diagram_class.project_id, command.user_id
        )

        # 3. Aplicar mutaciones en la entidad de dominio (valida invariantes y protege PK)
        attribute.update_details(
            name=command.name,
            data_type=command.data_type,
            is_nullable=command.is_nullable,
        )

        # 4. Persistir y confirmar transacción
        self.diagram_attribute_repository.save(attribute)
        self.uow.publish_event(DiagramAttributeUpdatedEvent(
            project_id=diagram_class.project_id, sender_id=command.user_id,
            data={"class_id": str(attribute.class_id), "attribute_id": str(attribute.id),
                  "name": attribute.name, "data_type": attribute.data_type.value if attribute.data_type else None,
                  "is_nullable": attribute.is_nullable},
        ))
        self.uow.commit()

        return attribute
