"""Adaptadores relacionales que delegan efectos derivados al caso de uso de Diagram."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentReservationActivityType,
)
from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    RelationValidationIssueCode,
    are_relations_equivalent,
    is_structural,
)
from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
    AgentReservationEmitter,
)
from app.modules.assistant.application.services.diagram.diagram_class_tools import _report
from app.modules.assistant.application.services.diagram.diagram_layout_optimizer import (
    DiagramLayoutOptimizer,
)
from app.modules.assistant.application.services.execution.tool_registry import ProgressReporter
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.services.diagram_relation_materializer import (
    calculate_bridge_class_position,
    generate_bridge_class_name,
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
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType
from app.modules.diagram.domain.exceptions import (
    DiagramClassNotFoundException,
    DiagramRelationNotFoundException,
)
from app.modules.diagram.domain.services.diagram_relation_materialization_policy import (
    MaterializationStrategy,
    determine_materialization_plan,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
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


class DiagramRelationTools:
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
        access = ProjectAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
        )
        self.access_policy = DiagramAccessPolicy(
            project_repository=project_repository,
            project_member_repository=member_repository,
            project_access_policy=access,
        ).for_agent()
        self.layout_optimizer = DiagramLayoutOptimizer()
        self.batch_handle_usage: dict[tuple[UUID, DiagramRelationHandle], int] = defaultdict(int)

    async def apply(
        self,
        action: dict[str, Any],
        report: ProgressReporter | None,
        *,
        batch_handle_usage: dict[tuple[UUID, DiagramRelationHandle], int] | None = None,
    ) -> dict[str, Any]:
        kind = action["kind"]
        if kind == "CREATE_RELATION":
            return await self._create(action, report, batch_handle_usage=batch_handle_usage)
        if kind == "RENAME_RELATION":
            return await self._rename(action, report)
        if kind == "DELETE_RELATION":
            return await self._delete(action, report)
        raise ValueError("Acción de relación no admitida")

    def _ensure_class_scope(self, class_id: UUID) -> DiagramClass:
        model = self.session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.id == class_id,
                DiagramClassModel.project_id == self.project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).first()
        if model is None:
            raise DiagramClassNotFoundException()
        entity = self.class_repository.find_by_id(class_id)
        if entity is None:
            raise DiagramClassNotFoundException()
        return entity

    def _ensure_relation_scope(self, relation_id: UUID):
        relation = self.session.exec(
            select(DiagramRelationModel).where(
                DiagramRelationModel.id == relation_id,
                DiagramRelationModel.project_id == self.project_id,
                DiagramRelationModel.deleted_date.is_(None),
            )
        ).first()
        if relation is None:
            raise DiagramRelationNotFoundException()
        entity = self.relation_repository.find_by_id(relation_id)
        if entity is None:
            raise DiagramRelationNotFoundException()
        return entity

    async def _create(
        self,
        action: dict[str, Any],
        report: ProgressReporter | None,
        *,
        batch_handle_usage: dict[tuple[UUID, DiagramRelationHandle], int] | None = None,
    ) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        source_id, target_id = UUID(action["source_class_id"]), UUID(action["target_class_id"])
        source, target = self._ensure_class_scope(source_id), self._ensure_class_scope(target_id)
        source_attributes = self.attribute_repository.list_by_class_id(source_id)
        target_attributes = self.attribute_repository.list_by_class_id(target_id)
        relation_type = DiagramRelationType(action["relation_type"])
        if is_structural(relation_type) and source_id == target_id:
            raise ConflictException(
                "Las relaciones estructurales no pueden conectar una clase consigo misma.",
                code=RelationValidationIssueCode.RELATION_COMBINATION_INVALID.value,
            )
        source_cardinality = _cardinality(action.get("source_cardinality"))
        target_cardinality = _cardinality(action.get("target_cardinality"))
        if relation_type is DiagramRelationType.ASSOCIATION:
            if source_cardinality is None and target_cardinality is None:
                source_cardinality = DiagramCardinality.ZERO_OR_MORE
                target_cardinality = DiagramCardinality.EXACTLY_ONE
            elif source_cardinality is None:
                source_cardinality = DiagramCardinality.ZERO_OR_MORE
            elif target_cardinality is None:
                target_cardinality = DiagramCardinality.EXACTLY_ONE
        raw_name = action.get("name")
        name = (
            raw_name.strip()
            if isinstance(raw_name, str) and raw_name.strip()
            else "Nueva relación"
        ) if relation_type is DiagramRelationType.ASSOCIATION else ""
        existing_models = self.session.exec(
            select(DiagramRelationModel).where(
                DiagramRelationModel.project_id == self.project_id,
                DiagramRelationModel.deleted_date.is_(None),
            )
        ).all()
        matches = [
            item
            for item in existing_models
            if are_relations_equivalent(
                type1=relation_type,
                source1=str(source_id),
                target1=str(target_id),
                source_card1=source_cardinality.value if source_cardinality is not None else None,
                target_card1=target_cardinality.value if target_cardinality is not None else None,
                name1=name,
                type2=item.relation_type,
                source2=str(item.source_class_id),
                target2=str(item.target_class_id),
                source_card2=item.source_cardinality,
                target_card2=item.target_cardinality,
                name2=item.name,
            )
        ]
        if len(matches) > 1:
            raise ConflictException(
                "Hay varias relaciones equivalentes; selecciona una antes de continuar."
            )
        if matches:
            existing = matches[0]
            if self.reservation_emitter is not None:
                await self.reservation_emitter.reserve_relation(
                    existing.id,
                    AgentReservationActivityType.EDIT,
                    source_class_id=source_id,
                    target_class_id=target_id,
                    bridge_class_id=existing.bridge_class_id,
                )
            existing_name = existing.name or f"{source.name} ↔ {target.name}"
            refs = [{"type": "relation", "id": str(existing.id), "name": existing_name}]
            derived_refs: list[dict[str, str]] = []
            if existing.bridge_class_id is not None:
                bridge_ref = {"type": "class", "id": str(existing.bridge_class_id)}
                refs.append(bridge_ref)
                derived_refs.append(bridge_ref)
                bridge_attributes = self.attribute_repository.list_by_class_id(
                    existing.bridge_class_id
                )
                primary_key = next(
                    (attribute for attribute in bridge_attributes if attribute.is_primary_key),
                    None,
                )
                if primary_key is not None:
                    pk_ref = {"type": "attribute", "id": str(primary_key.id)}
                    refs.append(pk_ref)
                    derived_refs.append(pk_ref)
                for attribute in bridge_attributes:
                    if attribute.is_foreign_key:
                        fk_ref = {"type": "attribute", "id": str(attribute.id)}
                        refs.append(fk_ref)
                        derived_refs.append(fk_ref)
            for attribute in self.attribute_repository.list_by_relation_id(existing.id):
                rel_attr_ref = {"type": "attribute", "id": str(attribute.id)}
                refs.append(rel_attr_ref)
                derived_refs.append(rel_attr_ref)

            unique_refs: list[dict[str, str]] = []
            seen_refs: set[tuple[str, str]] = set()
            for r in refs:
                key = (r["type"], r["id"])
                if key not in seen_refs:
                    seen_refs.add(key)
                    unique_refs.append(r)

            unique_derived: list[dict[str, str]] = []
            seen_derived: set[tuple[str, str]] = set()
            for r in derived_refs:
                key = (r["type"], r["id"])
                if key not in seen_derived:
                    seen_derived.add(key)
                    unique_derived.append(r)

            effects: list[dict[str, Any]] = [
                {"type": "already_materialized", "bridge_class_id": str(existing.bridge_class_id)}
                if existing.bridge_class_id is not None
                else {"type": "already_materialized"},
                *unique_derived,
            ]
            await _report(
                report,
                action,
                status="validated",
                entity_refs=unique_refs,
                derived_effects=effects,
            )
            await _report(
                report,
                action,
                status="applied",
                entity_refs=unique_refs,
                derived_effects=effects,
            )
            return {"status": "applied", "entity_refs": unique_refs, "derived_effects": effects}
        raw_src_handle = action.get("source_handle")
        raw_tgt_handle = action.get("target_handle")
        explicit_src = DiagramRelationHandle(raw_src_handle) if raw_src_handle else None
        explicit_tgt = DiagramRelationHandle(raw_tgt_handle) if raw_tgt_handle else None

        usage_tracker = batch_handle_usage if batch_handle_usage is not None else self.batch_handle_usage
        if explicit_src is None or explicit_tgt is None or source_id == target_id:
            source_handle, target_handle = self.layout_optimizer.calculate_relation_handles(
                session=self.session,
                project_id=self.project_id,
                source_class_id=source_id,
                target_class_id=target_id,
                explicit_source_handle=explicit_src,
                explicit_target_handle=explicit_tgt,
                batch_handle_usage=usage_tracker,
            )
        else:
            source_handle = explicit_src
            target_handle = explicit_tgt
            usage_tracker[(source_id, source_handle)] += 1
            usage_tracker[(target_id, target_handle)] += 1
        relation_id = uuid4()
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_class(source_id, AgentReservationActivityType.EDIT)
            await self.reservation_emitter.reserve_class(target_id, AgentReservationActivityType.EDIT)
        materialization = self._build_materialization(
            relation_id=relation_id,
            relation_type=relation_type,
            source=source,
            target=target,
            source_attributes=source_attributes,
            target_attributes=target_attributes,
            source_cardinality=source_cardinality,
            target_cardinality=target_cardinality,
        )
        derived_refs = _materialization_refs(relation_id, materialization)
        rel_display_name = name or f"{source.name} ↔ {target.name}"
        await _report(
            report,
            action,
            status="validated",
            entity_refs=[{"type": "relation", "id": str(relation_id), "name": rel_display_name}, *derived_refs],
            derived_effects=derived_refs,
        )
        relation, _created = CreateDiagramRelationUseCase(
            self.access_policy,
            self.class_repository,
            self.attribute_repository,
            self.relation_repository,
            self.uow,
        ).execute(
            CreateDiagramRelationCommand(
                id=relation_id,
                project_id=self.project_id,
                user_id=self.user_id,
                name=name,
                relation_type=relation_type,
                source_class_id=source_id,
                target_class_id=target_id,
                source_handle=source_handle,
                target_handle=target_handle,
                source_cardinality=source_cardinality,
                target_cardinality=target_cardinality,
                materialization=materialization,
                event_sender_id="assistant",
            )
        )
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_relation(
                relation.id,
                AgentReservationActivityType.EDIT,
                source_class_id=source_id,
                target_class_id=target_id,
                bridge_class_id=relation.bridge_class_id,
            )
        applied_name = relation.name or rel_display_name
        refs = [{"type": "relation", "id": str(relation.id), "name": applied_name}, *derived_refs]
        await _report(
            report, action, status="applied", entity_refs=refs, derived_effects=derived_refs
        )
        return {
            "status": "applied",
            "entity_refs": refs,
            "derived_effects": derived_refs,
        }

    def _build_materialization(
        self,
        *,
        relation_id: UUID,
        relation_type: DiagramRelationType,
        source: DiagramClass,
        target: DiagramClass,
        source_attributes: list,
        target_attributes: list,
        source_cardinality: DiagramCardinality | None,
        target_cardinality: DiagramCardinality | None,
    ) -> dict[str, Any]:
        plan = determine_materialization_plan(
            relation_type=relation_type,
            source_class_id=source.id,
            target_class_id=target.id,
            source_attributes_count=len(source_attributes),
            target_attributes_count=len(target_attributes),
            source_cardinality=source_cardinality,
            target_cardinality=target_cardinality,
        )
        materialization: dict[str, Any] = {
            "strategy": plan.strategy.value,
            "foreign_attributes": [],
            "shared_primary_key": None,
            "bridge_class": None,
        }
        if plan.strategy is MaterializationStrategy.FOREIGN_KEY:
            rule = plan.foreign_key
            assert rule is not None
            receiving = source if rule.receiving_class_id == source.id else target
            referenced = source if rule.referenced_class_id == source.id else target
            receiving_attributes = (
                source_attributes if receiving.id == source.id else target_attributes
            )
            materialization["foreign_attributes"] = [
                {
                    "id": str(uuid4()),
                    "class_id": str(receiving.id),
                    "name": _foreign_key_name(
                        referenced.name, [attribute.name for attribute in receiving_attributes]
                    ),
                    "data_type": "UUID",
                    "position": max((attribute.position for attribute in receiving_attributes), default=0) + 1,
                    "is_primary_key": False,
                    "is_foreign_key": True,
                    "is_nullable": rule.is_nullable,
                    "referenced_class_id": str(referenced.id),
                    "relation_id": str(relation_id),
                }
            ]
        elif plan.strategy is MaterializationStrategy.SHARED_PRIMARY_KEY:
            rule = plan.shared_primary_key
            assert rule is not None
            pk = next(
                (
                    attribute
                    for attribute in source_attributes
                    if attribute.is_primary_key and attribute.class_id == rule.subclass_id
                ),
                None,
            )
            if pk is None:
                raise DiagramClassNotFoundException()
            materialization["shared_primary_key"] = {
                "attribute_id": str(pk.id),
                "class_id": str(rule.subclass_id),
                "referenced_class_id": str(rule.superclass_id),
                "relation_id": str(relation_id),
            }
        elif plan.strategy is MaterializationStrategy.BRIDGE_CLASS:
            existing_classes = self.class_repository.list_by_project_id(self.project_id)
            bridge_id, pk_id, fk_source_id, fk_target_id = uuid4(), uuid4(), uuid4(), uuid4()
            bridge_name = generate_bridge_class_name(
                source.name, target.name, {item.name for item in existing_classes}
            )
            position_x, position_y = calculate_bridge_class_position(
                source.position_x,
                source.position_y,
                target.position_x,
                target.position_y,
            )
            if source.id == target.id:
                base = _snake_name(source.name)
                source_fk_name = f"{base}_a_id"
                target_fk_name = f"{base}_b_id"
            else:
                source_fk_name = _foreign_key_name(source.name, [])
                target_fk_name = _foreign_key_name(target.name, [source_fk_name])
            materialization["bridge_class"] = {
                "id": str(bridge_id),
                "name": bridge_name,
                "position_x": position_x,
                "position_y": position_y,
                "handle": DiagramRelationHandle.TOP_CENTER.value,
                "primary_attribute": {
                    "id": str(pk_id),
                    "name": "id",
                    "data_type": "UUID",
                    "position": 0,
                    "is_primary_key": True,
                    "is_nullable": False,
                },
                "foreign_attributes": [
                    _bridge_fk(
                        fk_source_id,
                        bridge_id,
                        source.id,
                        relation_id,
                        source_fk_name,
                        1,
                    ),
                    _bridge_fk(
                        fk_target_id,
                        bridge_id,
                        target.id,
                        relation_id,
                        target_fk_name,
                        2,
                    ),
                ],
            }
        return materialization

    async def _rename(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        relation_id = UUID(action["relation_id"])
        relation = self._ensure_relation_scope(relation_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_relation(
                relation.id,
                AgentReservationActivityType.EDIT,
                source_class_id=relation.source_class_id,
                target_class_id=relation.target_class_id,
                bridge_class_id=relation.bridge_class_id,
            )
        await _report(
            report, action, status="validated", entity_refs=[{"type": "relation", "id": str(relation_id)}]
        )
        relation = RenameDiagramRelationUseCase(
            self.access_policy, self.relation_repository, self.uow
        ).execute(
            RenameDiagramRelationCommand(
                relation_id=relation_id,
                user_id=self.user_id,
                name=action["name"],
                event_sender_id="assistant",
            )
        )
        refs = [{"type": "relation", "id": str(relation.id)}]
        await _report(report, action, status="applied", entity_refs=refs)
        return {"status": "applied", "entity_refs": refs}

    async def _delete(self, action: dict[str, Any], report: ProgressReporter | None) -> dict[str, Any]:
        self.access_policy.ensure_write_access(self.project_id, self.user_id)
        relation_id = UUID(action["relation_id"])
        relation = self._ensure_relation_scope(relation_id)
        if self.reservation_emitter is not None:
            await self.reservation_emitter.reserve_relation(
                relation.id,
                AgentReservationActivityType.EDIT,
                source_class_id=relation.source_class_id,
                target_class_id=relation.target_class_id,
                bridge_class_id=relation.bridge_class_id,
            )
        derived_refs = [
            {"type": "attribute", "id": str(attribute.id)}
            for attribute in self.attribute_repository.list_by_relation_id(relation_id)
        ]
        if relation.bridge_class_id is not None:
            derived_refs.append({"type": "class", "id": str(relation.bridge_class_id)})
        refs = [{"type": "relation", "id": str(relation_id)}, *derived_refs]
        await _report(
            report,
            action,
            status="validated",
            entity_refs=refs,
            derived_effects=derived_refs,
        )
        DeleteDiagramRelationUseCase(
            self.access_policy,
            self.relation_repository,
            self.class_repository,
            self.attribute_repository,
            self.uow,
        ).execute(
            DeleteDiagramRelationCommand(
                relation_id=relation_id,
                user_id=self.user_id,
                event_sender_id="assistant",
            )
        )
        await _report(
            report,
            action,
            status="applied",
            entity_refs=refs,
            derived_effects=derived_refs,
        )
        return {"status": "applied", "entity_refs": refs, "derived_effects": derived_refs}


def _cardinality(value: str | None) -> DiagramCardinality | None:
    if value is None:
        return None
    val_str = str(value).strip()
    if val_str in ("1..1", "1:1", "one", "uno"):
        return DiagramCardinality.EXACTLY_ONE
    if val_str in ("0..1", "0:1"):
        return DiagramCardinality.ZERO_OR_ONE
    if val_str in ("0..*", "0:*", "*", "N", "many", "muchos"):
        return DiagramCardinality.ZERO_OR_MORE
    if val_str in ("1..*", "1:*", "1..N"):
        return DiagramCardinality.ONE_OR_MORE
    try:
        return DiagramCardinality(val_str)
    except ValueError:
        return None


def _snake_name(name: str) -> str:
    value = re.sub(r"([A-Z])", r"_\1", name.strip()).replace("-", " ")
    value = re.sub(r"\s+", "_", value).lower().strip("_")
    return re.sub(r"_+", "_", value) or "ref"


def _foreign_key_name(referenced_name: str, existing_names: list[str]) -> str:
    base = _snake_name(referenced_name)
    base = base if base.endswith("_id") else f"{base}_id"
    existing = {name.casefold() for name in existing_names}
    if base.casefold() not in existing:
        return base
    suffix = 2
    while f"{base}_{suffix}".casefold() in existing:
        suffix += 1
    return f"{base}_{suffix}"


def _bridge_fk(
    attribute_id: UUID,
    bridge_id: UUID,
    referenced_id: UUID,
    relation_id: UUID,
    name: str,
    position: int,
) -> dict[str, Any]:
    return {
        "id": str(attribute_id),
        "class_id": str(bridge_id),
        "name": name,
        "data_type": "UUID",
        "position": position,
        "is_primary_key": False,
        "is_foreign_key": True,
        "is_nullable": False,
        "referenced_class_id": str(referenced_id),
        "relation_id": str(relation_id),
    }


def _materialization_refs(relation_id: UUID, value: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in value.get("foreign_attributes", []):
        refs.append({"type": "attribute", "id": str(item["id"])})
    shared = value.get("shared_primary_key")
    if shared:
        refs.append({"type": "attribute", "id": str(shared["attribute_id"])})
    bridge = value.get("bridge_class")
    if bridge:
        refs.append({"type": "class", "id": str(bridge["id"])})
        refs.append({"type": "attribute", "id": str(bridge["primary_attribute"]["id"])})
        refs.extend(
            {"type": "attribute", "id": str(item["id"])}
            for item in bridge.get("foreign_attributes", [])
        )
    return refs
