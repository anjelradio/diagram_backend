"""Adaptadores de atributos secundarios sobre los casos de uso de Diagram."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentReservationActivityType,
)
from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
    AgentReservationEmitter,
)
from app.modules.assistant.application.services.diagram.diagram_class_tools import _report
from app.modules.assistant.application.services.execution.tool_registry import ProgressReporter
from app.modules.assistant.domain.dialog.key_attribute_rules import (
    is_foreign_key_name,
    is_primary_key_name,
)
from app.modules.assistant.domain.dialog.slot_schema import (
    infer_attribute_nullability,
    infer_attribute_type,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
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
from app.modules.diagram.application.use_cases.diagram_attribute.reposition_diagram_attribute import (
    RepositionDiagramAttributeCommand,
    RepositionDiagramAttributeUseCase,
)
from app.modules.diagram.application.use_cases.diagram_attribute.update_diagram_attribute import (
    UNSET,
    UpdateDiagramAttributeCommand,
    UpdateDiagramAttributeUseCase,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.exceptions import (
    DiagramAttributeNotFoundException,
    DiagramClassNotFoundException,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.domain.exceptions import ConflictException
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


class DiagramAttributeTools:
    def __init__(
        self,
        session: Session,
        uow: SqlModelUnitOfWork,
        *,
        project_id: UUID,
        user_id: str,
        reservation_emitter: AgentReservationEmitter | None = None,
    ) -> None:
        self.session = session
        self.uow = uow
        self.project_id = project_id
        self.user_id = user_id
        self.reservation_emitter = reservation_emitter
        self.class_repository = SQLModelDiagramClassRepository(session)
        self.attribute_repository = SQLModelDiagramAttributeRepository(session)
        project_repository = SQLModelProjectRepository(session)
        member_repository = SQLModelProjectMemberRepository(session)
        access = ProjectAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
        )
        self.access_policy = DiagramAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
            project_access_policy=access,
        ).for_agent()

    async def apply(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        kind = action["kind"]
        if kind == "CREATE_ATTRIBUTE":
            return await self._create(action, report)
        if kind == "UPDATE_ATTRIBUTE":
            return await self._update(action, report)
        if kind == "REPOSITION_ATTRIBUTE":
            return await self._reposition(action, report)
        if kind == "DELETE_ATTRIBUTE":
            return await self._delete(action, report)
        raise ValueError("Acción de atributo no admitida")

    def _ensure_class_scope(self, class_id: UUID) -> DiagramClassModel:
        model = self.session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.id == class_id,
                DiagramClassModel.project_id == self.project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).first()
        if model is None:
            raise DiagramClassNotFoundException()
        return model

    def _ensure_attribute_scope(self, attribute_id: UUID) -> DiagramAttributeModel:
        row = self.session.exec(
            select(DiagramAttributeModel, DiagramClassModel)
            .join(DiagramClassModel, DiagramClassModel.id == DiagramAttributeModel.class_id)
            .where(
                DiagramAttributeModel.id == attribute_id,
                DiagramAttributeModel.deleted_date.is_(None),
                DiagramClassModel.project_id == self.project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).first()
        if row is None:
            raise DiagramAttributeNotFoundException()
        return row[0]

    async def _create(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        class_id = UUID(action["class_id"])
        class_model = self._ensure_class_scope(class_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                class_id, AgentReservationActivityType.EDIT
            )
        attribute_id = uuid4()
        attributes = self.attribute_repository.list_by_class_id(class_id)
        requested_name = action["name"].strip().casefold()
        existing_matches = [
            attribute
            for attribute in attributes
            if attribute.name.strip().casefold() == requested_name
            and (model := self.session.get(DiagramAttributeModel, attribute.id)) is not None
            and model.deleted_date is None
        ]
        if len(existing_matches) > 1:
            raise ConflictException(
                "Hay varios atributos con ese nombre; selecciona uno antes de continuar."
            )
        if existing_matches:
            existing = existing_matches[0]
            refs = [{"type": "attribute", "id": str(existing.id)}]
            if existing.is_primary_key or existing.is_foreign_key:
                effects = (
                    [{"type": "already_materialized", "by_relation_id": str(existing.relation_id)}]
                    if existing.relation_id
                    else [{"type": "already_materialized", "by_class": str(class_id)}]
                )
            else:
                effects = [{"type": "already_exists"}]
            await _report(
                report,
                action,
                status="validated",
                entity_refs=refs,
                derived_effects=effects,
            )
            await _report(
                report,
                action,
                status="applied",
                entity_refs=refs,
                derived_effects=effects,
            )
            return {"status": "applied", "entity_refs": refs, "derived_effects": effects}

        # Ignorar o vincular a la PK existente si el atributo solicitado es candidato a PK
        if is_primary_key_name(action["name"], class_model.name):
            existing_pk = next((a for a in attributes if a.is_primary_key), None)
            refs = [{"type": "attribute", "id": str(existing_pk.id)}] if existing_pk else []
            effects = [{"type": "already_materialized", "by_class": str(class_id)}]
            await _report(report, action, status="applied", entity_refs=refs, derived_effects=effects)
            return {"status": "applied", "entity_refs": refs, "derived_effects": effects}

        # Las llaves foráneas nacen exclusivamente de relaciones; ignorar creación secundaria manual
        if is_foreign_key_name(action["name"], class_model.name):
            effects = [{"type": "foreign_key_ignored", "note": "foreign_key_created_with_relation"}]
            await _report(report, action, status="applied", entity_refs=[], derived_effects=effects)
            return {"status": "applied", "entity_refs": [], "derived_effects": effects}

        position = action.get("position", len(attributes))
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[{"type": "attribute", "id": str(attribute_id)}],
        )
        attribute, _created = CreateDiagramAttributeUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            CreateDiagramAttributeCommand(
                id=attribute_id,
                class_id=class_id,
                user_id=self.user_id,
                name=action["name"],
                position=position,
                data_type=(
                    DiagramAttributeDataType(action["data_type"])
                    if action.get("data_type") is not None
                    else DiagramAttributeDataType(infer_attribute_type(action.get("name")))
                ),
                is_nullable=(
                    action["nullable"]
                    if action.get("nullable") is not None
                    else infer_attribute_nullability(action.get("name"))
                ),
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "attribute", "id": str(attribute.id)}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}

    async def _update(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        attribute_id = UUID(action["attribute_id"])
        attribute_model = self._ensure_attribute_scope(attribute_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                attribute_model.class_id,
                AgentReservationActivityType.EDIT,
                attribute_id=attribute_id,
            )
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[{"type": "attribute", "id": str(attribute_id)}],
        )
        attribute = UpdateDiagramAttributeUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            UpdateDiagramAttributeCommand(
                attribute_id=attribute_id,
                user_id=self.user_id,
                name=action.get("name", UNSET),
                data_type=(
                    DiagramAttributeDataType(action["data_type"])
                    if "data_type" in action and action["data_type"] is not None
                    else None
                    if "data_type" in action
                    else UNSET
                ),
                is_nullable=action.get("nullable", UNSET),
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "attribute", "id": str(attribute.id)}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}

    async def _reposition(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        attribute_id = UUID(action["attribute_id"])
        attribute_model = self._ensure_attribute_scope(attribute_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                attribute_model.class_id,
                AgentReservationActivityType.EDIT,
                attribute_id=attribute_id,
            )
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[{"type": "attribute", "id": str(attribute_id)}],
        )
        RepositionDiagramAttributeUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            RepositionDiagramAttributeCommand(
                attribute_id=attribute_id,
                user_id=self.user_id,
                target_position=action["position"],
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "attribute", "id": str(attribute_id)}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}

    async def _delete(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        attribute_id = UUID(action["attribute_id"])
        attribute_model = self._ensure_attribute_scope(attribute_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                attribute_model.class_id,
                AgentReservationActivityType.EDIT,
                attribute_id=attribute_id,
            )
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[{"type": "attribute", "id": str(attribute_id)}],
        )
        DeleteDiagramAttributeUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            DeleteDiagramAttributeCommand(
                attribute_id=attribute_id,
                user_id=self.user_id,
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "attribute", "id": str(attribute_id)}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}
