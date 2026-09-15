import logging
from typing import Any

from app.modules.assistant.application.services.action_planner import (
    ValidatedAction,
)
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.use_cases.diagram_attribute.create_diagram_attribute import (
    CreateDiagramAttributeCommand,
    CreateDiagramAttributeUseCase,
)
from app.modules.diagram.application.use_cases.diagram_attribute.delete_diagram_attribute import (
    DeleteDiagramAttributeCommand,
    DeleteDiagramAttributeUseCase,
)
from app.modules.diagram.application.use_cases.diagram_attribute.update_diagram_attribute import (
    UpdateDiagramAttributeCommand,
    UpdateDiagramAttributeUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.create_diagram_class import (
    CreateDiagramClassCommand,
    CreateDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.delete_diagram_class import (
    DeleteDiagramClassCommand,
    DeleteDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.rename_diagram_class import (
    RenameDiagramClassCommand,
    RenameDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_relation.create_diagram_relation import (
    CreateDiagramRelationCommand,
    CreateDiagramRelationUseCase,
)
from app.modules.diagram.application.use_cases.diagram_relation.delete_diagram_relation import (
    DeleteDiagramRelationCommand,
    DeleteDiagramRelationUseCase,
)
from app.modules.diagram.application.use_cases.diagram_relation.rename_diagram_relation import (
    RenameDiagramRelationCommand,
    RenameDiagramRelationUseCase,
)
from app.modules.diagram.domain.entities.diagram_attribute import UNSET
from app.modules.diagram.domain.events.diagram_events import DiagramMutationEvent
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
)
from app.shared.domain.domain_event import DomainEvent
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork

logger = logging.getLogger(__name__)


class AtomicBatchUnitOfWork:
    """Envuelve a SqlModelUnitOfWork para asegurar que un lote de use cases se ejecute en una sola transacción atómica."""

    def __init__(self, real_uow: SqlModelUnitOfWork) -> None:
        self.real_uow = real_uow
        self.collected_events: list[DiagramMutationEvent] = []

    def publish_event(self, event: DomainEvent) -> None:
        if isinstance(event, DiagramMutationEvent):
            self.collected_events.append(event)
        else:
            self.real_uow.publish_event(event)

    def commit(self) -> None:
        """Realiza un flush para que los use cases subsiguientes del lote vean los cambios sin confirmar la transacción."""
        self.real_uow.flush()

    def flush(self) -> None:
        """Sincroniza el lote sin confirmarlo para que las acciones siguientes lo vean."""
        self.real_uow.flush()

    def rollback(self) -> None:
        self.real_uow.rollback()
        self.collected_events.clear()


class ActionExecutor:
    """Ejecuta acciones validadas delegando en los use cases existentes del módulo diagram."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        diagram_relation_repository: DiagramRelationRepository,
        batch_uow: AtomicBatchUnitOfWork,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.diagram_relation_repository = diagram_relation_repository
        self.batch_uow = batch_uow
        self.agent_access_policy = access_policy.for_agent()

        # Casos de uso de relación
        self.create_rel_uc = CreateDiagramRelationUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            diagram_relation_repository=diagram_relation_repository,
            uow=batch_uow,
        )
        self.delete_rel_uc = DeleteDiagramRelationUseCase(
            access_policy=self.agent_access_policy,
            diagram_relation_repository=diagram_relation_repository,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            uow=batch_uow,
        )
        self.rename_rel_uc = RenameDiagramRelationUseCase(
            access_policy=self.agent_access_policy,
            diagram_relation_repository=diagram_relation_repository,
            uow=batch_uow,
        )

        # Casos de uso de clase
        self.create_class_uc = CreateDiagramClassUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            uow=batch_uow,
        )
        self.delete_class_uc = DeleteDiagramClassUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_relation_repository=diagram_relation_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            delete_diagram_relation_use_case=self.delete_rel_uc,
            uow=batch_uow,
        )
        self.rename_class_uc = RenameDiagramClassUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            uow=batch_uow,
        )

        # Casos de uso de atributo
        self.create_attr_uc = CreateDiagramAttributeUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            uow=batch_uow,
        )
        self.update_attr_uc = UpdateDiagramAttributeUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            uow=batch_uow,
        )
        self.delete_attr_uc = DeleteDiagramAttributeUseCase(
            access_policy=self.agent_access_policy,
            diagram_class_repository=diagram_class_repository,
            diagram_attribute_repository=diagram_attribute_repository,
            uow=batch_uow,
        )

    def execute_action(self, action: ValidatedAction) -> None:
        p = action.payload

        if action.action_type == AgentActionType.CREATE_CLASS:
            cmd = CreateDiagramClassCommand(
                id=p["id"],
                project_id=p["project_id"],
                user_id=p["user_id"],
                name=p["name"],
                position_x=p["position_x"],
                position_y=p["position_y"],
                primary_attribute_id=p["primary_attribute_id"],
                primary_attribute_name=p.get("primary_attribute_name", "id"),
            )
            self.create_class_uc.execute(cmd)

        elif action.action_type == AgentActionType.DELETE_CLASS:
            cmd = DeleteDiagramClassCommand(
                class_id=p["class_id"],
                user_id=p["user_id"],
            )
            self.delete_class_uc.execute(cmd)

        elif action.action_type == AgentActionType.RENAME_CLASS:
            cmd = RenameDiagramClassCommand(
                class_id=p["class_id"],
                user_id=p["user_id"],
                new_name=p["new_name"],
            )
            self.rename_class_uc.execute(cmd)

        elif action.action_type == AgentActionType.CREATE_ATTRIBUTE:
            cmd = CreateDiagramAttributeCommand(
                id=p["id"],
                class_id=p["class_id"],
                user_id=p["user_id"],
                name=p["name"],
                position=p["position"],
                data_type=p.get("data_type"),
                is_nullable=p.get("is_nullable", True),
            )
            self.create_attr_uc.execute(cmd)

        elif action.action_type == AgentActionType.UPDATE_ATTRIBUTE:
            cmd = UpdateDiagramAttributeCommand(
                attribute_id=p["attribute_id"],
                user_id=p["user_id"],
                name=p["new_name"] if p.get("new_name") else UNSET,
                data_type=p["new_data_type"] if p.get("new_data_type") else UNSET,
                is_nullable=p["is_nullable"] if p.get("is_nullable") is not None else UNSET,
            )
            self.update_attr_uc.execute(cmd)

        elif action.action_type == AgentActionType.DELETE_ATTRIBUTE:
            cmd = DeleteDiagramAttributeCommand(
                attribute_id=p["attribute_id"],
                user_id=p["user_id"],
            )
            self.delete_attr_uc.execute(cmd)

        elif action.action_type == AgentActionType.CREATE_RELATION:
            cmd = CreateDiagramRelationCommand(
                id=p["id"],
                project_id=p["project_id"],
                user_id=p["user_id"],
                name=p["name"],
                relation_type=p["relation_type"],
                source_class_id=p["source_class_id"],
                target_class_id=p["target_class_id"],
                source_handle=p["source_handle"],
                target_handle=p["target_handle"],
                source_cardinality=p["source_cardinality"],
                target_cardinality=p["target_cardinality"],
                materialization=p["materialization"],
            )
            self.create_rel_uc.execute(cmd)

        elif action.action_type == AgentActionType.DELETE_RELATION:
            cmd = DeleteDiagramRelationCommand(
                relation_id=p["relation_id"],
                user_id=p["user_id"],
            )
            self.delete_rel_uc.execute(cmd)

        elif action.action_type == AgentActionType.RENAME_RELATION:
            cmd = RenameDiagramRelationCommand(
                relation_id=p["relation_id"],
                user_id=p["user_id"],
                new_name=p["new_name"],
            )
            self.rename_rel_uc.execute(cmd)
