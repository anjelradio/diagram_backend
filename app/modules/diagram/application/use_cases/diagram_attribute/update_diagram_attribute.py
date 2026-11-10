from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.services.diagram_audit_serializer import (
    create_diagram_audit_event,
    serialize_attribute,
)
from app.modules.diagram.domain.entities.diagram_attribute import UNSET, DiagramAttribute
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditEntityType,
)
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
from app.shared.application.unit_of_work import UnitOfWorkPort
from app.modules.diagram.domain.events.diagram_events import DiagramAttributeUpdatedEvent


@dataclass(frozen=True, slots=True)
class UpdateDiagramAttributeCommand:
    """Comando para actualizar detalles editables de un atributo."""

    attribute_id: UUID
    user_id: str
    name: str | object = UNSET
    data_type: DiagramAttributeDataType | None | object = UNSET
    is_nullable: bool | object = UNSET
    event_sender_id: str | None = None


class UpdateDiagramAttributeUseCase:
    """Caso de uso para actualizar parcialmente los detalles de un atributo protegiendo la PK."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        uow: UnitOfWorkPort,
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

        payload_before = serialize_attribute(attribute, class_name=diagram_class.name)

        # 3. Aplicar mutaciones en la entidad de dominio (valida invariantes y protege PK)
        attribute.update_details(
            name=command.name,
            data_type=command.data_type,
            is_nullable=command.is_nullable,
        )

        payload_after = serialize_attribute(attribute, class_name=diagram_class.name)

        # 4. Persistir y confirmar transacción
        self.diagram_attribute_repository.save(attribute)
        self.uow.publish_event(DiagramAttributeUpdatedEvent(
            project_id=diagram_class.project_id, sender_id=command.event_sender_id or command.user_id,
            data={"class_id": str(attribute.class_id), "attribute_id": str(attribute.id),
                  "name": attribute.name, "data_type": attribute.data_type.value if attribute.data_type else None,
                  "is_nullable": attribute.is_nullable},
        ))
        if payload_before != payload_after:
            self.uow.publish_event(
                create_diagram_audit_event(
                    project_id=diagram_class.project_id,
                    user_id=command.user_id,
                    event_sender_id=command.event_sender_id,
                    entity_type=DiagramAuditEntityType.ATTRIBUTE,
                    entity_id=attribute.id,
                    entity_name=attribute.name,
                    parent_class_id=diagram_class.id,
                    parent_class_name=diagram_class.name,
                    action=DiagramAuditAction.UPDATE,
                    use_case="UPDATE_ATTRIBUTE",
                    summary=f"Se modificó el atributo '{attribute.name}' en la clase '{diagram_class.name}'",
                    payload_before=payload_before,
                    payload_after=payload_after,
                )
            )
        self.uow.commit()

        return attribute

