"""Adaptadores de clases del agente sobre los casos de uso de Diagram."""

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
from app.modules.assistant.application.services.diagram.diagram_layout_optimizer import (
    DiagramLayoutOptimizer,
)
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
from app.modules.diagram.application.use_cases.diagram_relation.delete_diagram_relation import (
    DeleteDiagramRelationCommand,
    DeleteDiagramRelationUseCase,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.exceptions import DiagramClassNotFoundException
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.domain.exceptions import ConflictException
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


class DiagramClassTools:
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
        self.relation_repository = SQLModelDiagramRelationRepository(session)
        project_repository = SQLModelProjectRepository(session)
        member_repository = SQLModelProjectMemberRepository(session)
        base_access = ProjectAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
        )
        self.access_policy = DiagramAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
            project_access_policy=base_access,
        ).for_agent()
        self.delete_relation = DeleteDiagramRelationUseCase(
            self.access_policy,
            self.relation_repository,
            self.class_repository,
            self.attribute_repository,
            uow,
        )
        self.layout_optimizer = DiagramLayoutOptimizer()
        self.batch_reserved_positions: list[tuple[float, float]] = []

    async def apply(
        self,
        action: dict[str, Any],
        report: ProgressReporter | None,
        *,
        selected_class_id: str | None = None,
        reference_class_id: UUID | None = None,
        batch_reserved_positions: list[tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        kind = action["kind"]
        if kind == "CREATE_CLASS":
            return await self._create(
                action,
                report,
                selected_class_id=selected_class_id,
                reference_class_id=reference_class_id,
                batch_reserved_positions=batch_reserved_positions,
            )
        if kind == "RENAME_CLASS":
            return await self._rename(action, report)
        if kind == "DELETE_CLASS":
            return await self._delete(action, report)
        raise ValueError("Acción de clase no admitida")

    def _ensure_active_class(self, class_id: UUID) -> DiagramClassModel:
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

    async def _create(
        self,
        action: dict[str, Any],
        report: ProgressReporter | None,
        *,
        selected_class_id: str | None = None,
        reference_class_id: UUID | None = None,
        batch_reserved_positions: list[tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        classes = self.class_repository.list_by_project_id(self.project_id)
        name = action.get("name") or "Nueva clase"
        existing_models = self.session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == self.project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).all()
        matches = [
            item
            for item in existing_models
            if item.name.strip().casefold() == name.strip().casefold()
        ]
        if selected_class_id is not None:
            matches = [item for item in matches if str(item.id) == selected_class_id]
            if len(matches) != 1:
                raise ConflictException("La clase elegida ya no está disponible.")
        elif len(matches) > 1:
            raise ConflictException(
                "Hay varias clases con ese nombre; selecciona una antes de continuar."
            )
        if matches:
            existing = matches[0]
            if self.reservation_emitter is not None:
                await self.reservation_emitter.reserve_class(
                    existing.id, AgentReservationActivityType.EDIT
                )
            owning_relation = self.relation_repository.find_by_bridge_class_id(existing.id)
            if owning_relation is not None and owning_relation.project_id != self.project_id:
                owning_relation = None
            existing_attributes = self.attribute_repository.list_by_class_id(existing.id)
            primary_key = next(
                (attribute for attribute in existing_attributes if attribute.is_primary_key),
                None,
            )
            refs = [{"type": "class", "id": str(existing.id), "name": existing.name}]
            if primary_key is not None:
                refs.append({"type": "attribute", "id": str(primary_key.id)})
            effects = (
                [{"type": "already_materialized", "by_relation_id": str(owning_relation.id)}]
                if owning_relation is not None
                else [{"type": "already_exists"}]
            )
            raw_attributes = action.get("attributes")
            if isinstance(raw_attributes, list):
                attr_use_case = CreateDiagramAttributeUseCase(
                    self.access_policy,
                    self.class_repository,
                    self.attribute_repository,
                    self.uow,
                )
                next_pos = len(existing_attributes)
                for attr_spec in raw_attributes:
                    if not isinstance(attr_spec, dict):
                        continue
                    attr_name = (attr_spec.get("name") or "").strip()
                    if not attr_name:
                        continue
                    if is_primary_key_name(attr_name, existing.name):
                        effects.append({"type": "already_materialized", "by_class": str(existing.id)})
                    elif is_foreign_key_name(attr_name, existing.name):
                        effects.append({"type": "foreign_key_ignored", "note": "foreign_key_created_with_relation"})
                    elif any(a.name.strip().casefold() == attr_name.casefold() for a in existing_attributes):
                        effects.append({"type": "already_exists", "name": attr_name})
                    else:
                        attr_id = uuid4()
                        data_type = (
                            DiagramAttributeDataType.from_raw(attr_spec["data_type"])
                            if attr_spec.get("data_type") is not None
                            else DiagramAttributeDataType.from_raw(infer_attribute_type(attr_name))
                        )
                        created_attr, _ = attr_use_case.execute(
                            CreateDiagramAttributeCommand(
                                id=attr_id,
                                class_id=existing.id,
                                user_id=self.user_id,
                                name=attr_name,
                                position=next_pos,
                                data_type=data_type,
                                is_nullable=(
                                    attr_spec["nullable"]
                                    if attr_spec.get("nullable") is not None
                                    else infer_attribute_nullability(attr_name)
                                ),
                                event_sender_id="assistant",
                            )
                        )
                        next_pos += 1
                        refs.append({"type": "attribute", "id": str(created_attr.id)})
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

        class_id, primary_id = uuid4(), uuid4()
        position = action.get("position")
        reserved = (
            batch_reserved_positions
            if batch_reserved_positions is not None
            else self.batch_reserved_positions
        )
        if position is None:
            ref_id = reference_class_id or action.get("_reference_class_id")
            position_x, position_y = self.layout_optimizer.calculate_class_position(
                session=self.session,
                project_id=self.project_id,
                reference_class_id=ref_id,
                batch_reserved_positions=reserved,
            )
        else:
            position_x, position_y = float(position["x"]), float(position["y"])
            reserved.append((position_x, position_y))
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[
                {"type": "class", "id": str(class_id), "name": name},
                {"type": "attribute", "id": str(primary_id)},
            ],
        )
        diagram_class, attributes, _created = CreateDiagramClassUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            CreateDiagramClassCommand(
                id=class_id,
                project_id=self.project_id,
                user_id=self.user_id,
                name=name,
                position_x=position_x,
                position_y=position_y,
                primary_attribute_id=primary_id,
                event_sender_id="assistant",
            )
        )
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                diagram_class.id, AgentReservationActivityType.EDIT
            )
        refs = [
            {"type": "class", "id": str(diagram_class.id), "name": diagram_class.name},
            {"type": "attribute", "id": str(attributes[0].id)},
        ]
        derived_effects: list[dict[str, str]] = []
        raw_attributes = action.get("attributes")
        if isinstance(raw_attributes, list):
            attr_use_case = CreateDiagramAttributeUseCase(
                self.access_policy,
                self.class_repository,
                self.attribute_repository,
                self.uow,
            )
            next_pos = len(attributes)
            for attr_spec in raw_attributes:
                if not isinstance(attr_spec, dict):
                    continue
                attr_name = (attr_spec.get("name") or "").strip()
                if not attr_name:
                    continue
                if is_primary_key_name(attr_name, diagram_class.name):
                    derived_effects.append({
                        "type": "already_materialized",
                        "by_class": str(diagram_class.id),
                    })
                    continue
                if is_foreign_key_name(attr_name, diagram_class.name):
                    derived_effects.append({
                        "type": "foreign_key_ignored",
                        "note": "foreign_key_created_with_relation",
                    })
                    continue
                attr_id = uuid4()
                data_type = (
                    DiagramAttributeDataType.from_raw(attr_spec["data_type"])
                    if attr_spec.get("data_type") is not None
                    else DiagramAttributeDataType.from_raw(infer_attribute_type(attr_name))
                )
                created_attr, _ = attr_use_case.execute(
                    CreateDiagramAttributeCommand(
                        id=attr_id,
                        class_id=diagram_class.id,
                        user_id=self.user_id,
                        name=attr_name,
                        position=next_pos,
                        data_type=data_type,
                        is_nullable=(
                            attr_spec["nullable"]
                            if attr_spec.get("nullable") is not None
                            else infer_attribute_nullability(attr_name)
                        ),
                        event_sender_id="assistant",
                    )
                )
                next_pos += 1
                refs.append({"type": "attribute", "id": str(created_attr.id)})

        await _report(report, action, status="applied", entity_refs=refs, derived_effects=derived_effects)
        return {"status": "applied", "entity_refs": refs, "derived_effects": derived_effects}

    async def _rename(
        self, action: dict[str, Any], report: ProgressReporter | None
    ) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        class_id = UUID(action["class_id"])
        self._ensure_active_class(class_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                class_id, AgentReservationActivityType.EDIT
            )
        await _report(
            report, action, status="validated", entity_refs=[{"type": "class", "id": str(class_id)}]
        )
        result = RenameDiagramClassUseCase(
            self.access_policy, self.class_repository, self.uow
        ).execute(
            RenameDiagramClassCommand(
                class_id=class_id,
                user_id=self.user_id,
                name=action["name"],
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "class", "id": str(result.id), "name": result.name}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}

    async def _delete(
        self, action: dict[str, Any], report: ProgressReporter | None
    ) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        class_id = UUID(action["class_id"])
        target_model = self._ensure_active_class(class_id)
        owning_relation = self.relation_repository.find_by_bridge_class_id(class_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(
                class_id, AgentReservationActivityType.EDIT
            )
            if owning_relation is not None:
                await self.reservation_emitter.reserve_relation(
                    owning_relation.id, AgentReservationActivityType.EDIT
                )
        if owning_relation is not None:
            if owning_relation.project_id != self.project_id:
                raise DiagramClassNotFoundException()
            await _report(
                report,
                action,
                status="validated",
                entity_refs=[
                    {"type": "class", "id": str(class_id), "name": target_model.name},
                    {"type": "relation", "id": str(owning_relation.id)},
                ],
            )
            self.delete_relation.execute(
                DeleteDiagramRelationCommand(
                    relation_id=owning_relation.id,
                    user_id=self.user_id,
                    event_sender_id="assistant",
                )
            )
            refs = [{"type": "relation", "id": str(owning_relation.id)}]
            effects = [{"type": "deleted_bridge_class", "id": str(class_id)}]
        else:
            await _report(
                report,
                action,
                status="validated",
                entity_refs=[{"type": "class", "id": str(class_id), "name": target_model.name}],
            )
            DeleteDiagramClassUseCase(
                self.access_policy,
                self.class_repository,
                self.relation_repository,
                self.attribute_repository,
                self.delete_relation,
                self.uow,
            ).execute(
                DeleteDiagramClassCommand(
                    class_id=class_id,
                    user_id=self.user_id,
                    event_sender_id="assistant",
                )
            )
            refs = [{"type": "class", "id": str(class_id), "name": target_model.name}]
            effects = []
        await _report(
            report, action, status="applied", entity_refs=refs, derived_effects=effects
        )
        return {"status": "applied", "entity_refs": refs, "derived_effects": effects}


async def _report(
    reporter: ProgressReporter | None,
    action: dict[str, Any],
    *,
    status: str,
    entity_refs: list[dict[str, str]],
    derived_effects: list[dict[str, str]] | None = None,
) -> None:
    if reporter is None:
        return
    await reporter(
        {
            "operation_id": action["operation_id"],
            "action_kind": action["kind"],
            "status": status,
            "entity_refs": entity_refs,
            "derived_effects": derived_effects or [],
        }
    )
