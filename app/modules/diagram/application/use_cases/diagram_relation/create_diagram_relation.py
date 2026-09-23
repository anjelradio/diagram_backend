from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.services.diagram_relation_materializer import (
    MaterializationStrategy,
    determine_materialization_plan,
    validate_relation_materialization,
)
from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.domain.exceptions import (
    DiagramClassIdConflictException,
    DiagramClassNotFoundException,
    DiagramRelationIdConflictException,
    DiagramRelationSelfReferenceException,
    DuplicateGeneralizationException,
    InvalidDiagramRelationHandleException,
    InvalidDiagramRelationMaterializationException,
    SelfReferencingNonAssociationException,
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
from app.modules.diagram.domain.events.diagram_events import DiagramRelationCreatedEvent


@dataclass(frozen=True, slots=True)
class CreateDiagramRelationCommand:
    """Comando para crear una relación UML y su materialización atómica en el diagrama."""

    id: UUID
    project_id: UUID
    user_id: str
    name: str
    relation_type: DiagramRelationType
    source_class_id: UUID
    target_class_id: UUID
    source_handle: DiagramRelationHandle
    target_handle: DiagramRelationHandle
    source_cardinality: DiagramCardinality | None
    target_cardinality: DiagramCardinality | None
    materialization: dict[str, Any]


class CreateDiagramRelationUseCase:
    """Caso de uso para crear transaccionalmente el agregado relacional (relación, FK, puente)."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        diagram_relation_repository: DiagramRelationRepository,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.diagram_relation_repository = diagram_relation_repository
        self.uow = uow

    def execute(
        self, command: CreateDiagramRelationCommand
    ) -> tuple[DiagramRelation, bool]:
        """Ejecuta la creación atómica de la relación. Retorna (DiagramRelation, is_created)."""
        # 1. Autorización de escritura sobre el proyecto
        self.access_policy.ensure_write_access(command.project_id, command.user_id)

        # 2. Invariante de autorrelación
        if command.source_class_id == command.target_class_id:
            if command.relation_type != DiagramRelationType.ASSOCIATION:
                raise SelfReferencingNonAssociationException()
            if command.source_handle == command.target_handle:
                raise InvalidDiagramRelationHandleException(
                    "Una relación recursiva debe utilizar handles distintos en origen y destino."
                )

        # 3. Comprobar que las clases existan y pertenezcan al proyecto
        source_class = self.diagram_class_repository.find_by_id(command.source_class_id)
        if source_class is None or source_class.project_id != command.project_id:
            raise DiagramClassNotFoundException()

        target_class = self.diagram_class_repository.find_by_id(command.target_class_id)
        if target_class is None or target_class.project_id != command.project_id:
            raise DiagramClassNotFoundException()

        # 4. Comprobar idempotencia o conflicto por ID
        existing = self.diagram_relation_repository.find_by_id(command.id)
        if existing is not None:
            expected_name = (
                command.name.strip()
                if existing.relation_type == DiagramRelationType.ASSOCIATION
                else ""
            )
            is_exact_match = (
                existing.project_id == command.project_id
                and existing.source_class_id == command.source_class_id
                and existing.target_class_id == command.target_class_id
                and existing.relation_type == command.relation_type
                and existing.source_handle == command.source_handle
                and existing.target_handle == command.target_handle
                and existing.source_cardinality == command.source_cardinality
                and existing.target_cardinality == command.target_cardinality
                and existing.name == expected_name
            )
            if is_exact_match:
                bridge_data = command.materialization.get("bridge_class")
                if existing.is_many_to_many:
                    if (
                        bridge_data is None
                        or existing.bridge_class_id != UUID(str(bridge_data["id"]))
                    ):
                        raise DiagramRelationIdConflictException()
                return existing, False
            raise DiagramRelationIdConflictException()

        # 5. Restricción de generalización única por subclase en esta versión
        if command.relation_type == DiagramRelationType.GENERALIZATION:
            existing_gen = (
                self.diagram_relation_repository.find_active_generalization_by_source(
                    command.project_id, command.source_class_id
                )
            )
            if existing_gen is not None:
                raise DuplicateGeneralizationException()

        # 6. Calcular plan determinista y validar materialización provista por cliente
        source_attrs = self.diagram_attribute_repository.list_by_class_id(
            source_class.id
        )
        target_attrs = self.diagram_attribute_repository.list_by_class_id(
            target_class.id
        )

        plan = determine_materialization_plan(
            relation_type=command.relation_type,
            source_class_id=command.source_class_id,
            target_class_id=command.target_class_id,
            source_attributes_count=len(source_attrs),
            target_attributes_count=len(target_attrs),
            source_cardinality=command.source_cardinality,
            target_cardinality=command.target_cardinality,
        )

        validate_relation_materialization(
            relation_id=command.id,
            plan=plan,
            materialization_data=command.materialization,
        )

        # 7. Persistir artefactos en una sola transacción atómica
        bridge_class_id: UUID | None = None
        bridge_handle: DiagramRelationHandle | None = None

        if plan.strategy == MaterializationStrategy.BRIDGE_CLASS:
            bridge_data = command.materialization["bridge_class"]
            bridge_id = UUID(str(bridge_data["id"]))

            if self.diagram_class_repository.find_by_id(bridge_id) is not None:
                raise DiagramClassIdConflictException()

            bridge_class = DiagramClass.create(
                id=bridge_id,
                project_id=command.project_id,
                name=bridge_data["name"].strip(),
                position_x=float(bridge_data["position_x"]),
                position_y=float(bridge_data["position_y"]),
            )
            self.diagram_class_repository.save(bridge_class)
            bridge_class_id = bridge_id
            bridge_handle = DiagramRelationHandle(bridge_data["handle"])

        # Guardar primero la relación para satisfacer las referencias FK a relation_id
        relation = DiagramRelation.create(
            id=command.id,
            project_id=command.project_id,
            source_class_id=command.source_class_id,
            target_class_id=command.target_class_id,
            relation_type=command.relation_type,
            source_handle=command.source_handle,
            target_handle=command.target_handle,
            name=command.name,
            source_cardinality=command.source_cardinality,
            target_cardinality=command.target_cardinality,
            bridge_class_id=bridge_class_id,
            bridge_handle=bridge_handle,
        )
        self.diagram_relation_repository.save(relation)
        self.uow.flush()

        # Ahora persistir los atributos (PK y FK) que referencian a relation_id
        if plan.strategy == MaterializationStrategy.BRIDGE_CLASS:
            bridge_data = command.materialization["bridge_class"]
            bridge_id = UUID(str(bridge_data["id"]))
            pk_data = bridge_data["primary_attribute"]
            pk_attr = DiagramAttribute.create_primary_key(
                id=UUID(str(pk_data["id"])),
                class_id=bridge_id,
                name=pk_data["name"],
            )
            self.diagram_attribute_repository.save(pk_attr)

            for fa_data in bridge_data["foreign_attributes"]:
                fa_attr = DiagramAttribute.create_foreign_key(
                    id=UUID(str(fa_data["id"])),
                    class_id=bridge_id,
                    name=fa_data["name"],
                    position=int(fa_data["position"]),
                    referenced_class_id=UUID(str(fa_data["referenced_class_id"])),
                    relation_id=command.id,
                    is_nullable=False,
                )
                self.diagram_attribute_repository.save(fa_attr)

        elif plan.strategy == MaterializationStrategy.SHARED_PRIMARY_KEY:
            spk_data = command.materialization["shared_primary_key"]
            subclass_pk = next((a for a in source_attrs if a.is_primary_key), None)
            if (
                subclass_pk is None
                or subclass_pk.id != UUID(str(spk_data["attribute_id"]))
            ):
                raise InvalidDiagramRelationMaterializationException()

            subclass_pk.as_shared_primary_key(
                referenced_class_id=command.target_class_id,
                relation_id=command.id,
            )
            self.diagram_attribute_repository.save(subclass_pk)

        elif plan.strategy == MaterializationStrategy.FOREIGN_KEY:
            fa_data = command.materialization["foreign_attributes"][0]
            fa_attr = DiagramAttribute.create_foreign_key(
                id=UUID(str(fa_data["id"])),
                class_id=UUID(str(fa_data["class_id"])),
                name=fa_data["name"],
                position=int(fa_data["position"]),
                referenced_class_id=UUID(str(fa_data["referenced_class_id"])),
                relation_id=command.id,
                is_nullable=bool(fa_data["is_nullable"]),
            )
            self.diagram_attribute_repository.save(fa_attr)

        self.uow.publish_event(DiagramRelationCreatedEvent(
            project_id=command.project_id, sender_id=command.user_id,
            data={"id": str(relation.id), "name": relation.name,
                  "relation_type": relation.relation_type.value,
                  "source": {"class_id": str(relation.source_class_id), "handle": relation.source_handle.value,
                              "cardinality": relation.source_cardinality.value if relation.source_cardinality else None},
                  "target": {"class_id": str(relation.target_class_id), "handle": relation.target_handle.value,
                              "cardinality": relation.target_cardinality.value if relation.target_cardinality else None}},
        ))
        self.uow.commit()

        return relation, True
