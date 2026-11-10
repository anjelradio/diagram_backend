"""Catálogo de mutaciones autorizado para el proyecto del mensaje actual."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentComponentReservationPublisher,
)
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    RelationValidationIssueCode,
    are_relations_equivalent,
)
from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
    AgentReservationEmitter,
)
from app.modules.assistant.application.services.diagram.diagram_attribute_tools import (
    DiagramAttributeTools,
)
from app.modules.assistant.application.services.diagram.diagram_class_tools import (
    DiagramClassTools,
)
from app.modules.assistant.application.services.diagram.diagram_relation_tools import (
    DiagramRelationTools,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
    DIAGRAM_MUTATION_TOOL,
    validate_actions,
)
from app.modules.assistant.application.services.execution.terminal_failure import (
    map_to_terminal_tool_failure,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    ProgressReporter,
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import (
    AgentAmbiguousClassException,
    AgentMessagePersistenceException,
    AgentToolArgumentsException,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.shared.domain.exceptions import (
    ConflictException,
    DomainException,
    ForbiddenException,
    NotFoundException,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


class DiagramMutationTools:
    """Orquesta una lista ordenada; cada acción conserva el commit de su use case."""

    def __init__(
        self,
        session: Session,
        uow: SqlModelUnitOfWork,
        *,
        project_id: UUID,
        user_id: str,
        message_id: UUID | None = None,
        reservation_publisher: AgentComponentReservationPublisher | None = None,
        reservation_emitter: AgentReservationEmitter | None = None,
    ) -> None:
        if reservation_emitter is None and reservation_publisher is not None:
            reservation_emitter = AgentReservationEmitter(
                reservation_publisher,
                project_id=project_id,
                message_id=message_id,
            )
        self.reservation_emitter = reservation_emitter
        self.class_tools = DiagramClassTools(
            session,
            uow,
            project_id=project_id,
            user_id=user_id,
            reservation_emitter=reservation_emitter,
        )
        self.attribute_tools = DiagramAttributeTools(
            session,
            uow,
            project_id=project_id,
            user_id=user_id,
            reservation_emitter=reservation_emitter,
        )
        self.relation_tools = DiagramRelationTools(
            session,
            uow,
            project_id=project_id,
            user_id=user_id,
            reservation_emitter=reservation_emitter,
        )

    def register(self, registry: ToolRegistry) -> None:
        registry.register(
            RegisteredTool(
                DIAGRAM_MUTATION_TOOL,
                self.apply_diagram_changes,
                mutating=True,
                visual_scope_validator=self.validate_visual_scope,
                scoped_handler=self.apply_scoped_diagram_changes,
            )
        )

    def validate_visual_scope(
        self, arguments: dict[str, Any], evidence: dict[str, Any]
    ) -> None:
        """Revisa cada operación contra la evidencia visual autorizada por servidor."""
        self.class_tools.access_policy.ensure_write_access(
            self.class_tools.project_id, self.class_tools.user_id
        )
        actions = validate_actions(arguments)
        classes = evidence.get("classes")
        relations = evidence.get("relations")
        if not isinstance(classes, list) or not isinstance(relations, list):
            raise AgentToolArgumentsException()
        allowed_classes = {
            item["name"].strip().casefold()
            for item in classes
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        allowed_attributes = {
            item["name"].strip().casefold(): {
                attribute["name"].strip().casefold()
                for attribute in item.get("attributes", [])
                if isinstance(attribute, dict) and isinstance(attribute.get("name"), str)
            }
            for item in classes
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("attributes", []), list)
        }
        session = self.class_tools.session
        active_classes = session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == self.class_tools.project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).all()
        class_names = {str(item.id): item.name.strip().casefold() for item in active_classes}
        classes_by_name: dict[str, list[DiagramClassModel]] = {}
        for item in active_classes:
            classes_by_name.setdefault(item.name.strip().casefold(), []).append(item)
        selected_class_ids = evidence.get("selected_class_ids", {})
        if not isinstance(selected_class_ids, dict) or not all(
            isinstance(name, str) and isinstance(class_id, str)
            for name, class_id in selected_class_ids.items()
        ):
            raise AgentToolArgumentsException()
        attribute_ids = {
            UUID(action["attribute_id"])
            for action in actions
            if "attribute_id" in action
        }
        active_attributes = (
            session.exec(
                select(DiagramAttributeModel)
                .join(DiagramClassModel, DiagramClassModel.id == DiagramAttributeModel.class_id)
                .where(
                    DiagramAttributeModel.id.in_(attribute_ids),
                    DiagramClassModel.project_id == self.class_tools.project_id,
                    DiagramClassModel.deleted_date.is_(None),
                    DiagramAttributeModel.deleted_date.is_(None),
                )
            ).all()
            if attribute_ids
            else []
        )
        attributes_by_id = {str(item.id): item for item in active_attributes}
        relation_ids = {
            UUID(action["relation_id"])
            for action in actions
            if "relation_id" in action
        }
        active_relations = (
            session.exec(
                select(DiagramRelationModel).where(
                    DiagramRelationModel.id.in_(relation_ids),
                    DiagramRelationModel.project_id == self.class_tools.project_id,
                    DiagramRelationModel.deleted_date.is_(None),
                )
            ).all()
            if relation_ids
            else []
        )
        relations_by_id = {str(item.id): item for item in active_relations}

        for action in actions:
            kind = action["kind"]
            targets: list[tuple[str | None, str | None]] = []
            if kind == "CREATE_CLASS":
                class_name = action.get("name", "").strip().casefold()
                allowed = class_name in allowed_classes
                if allowed and "attributes" in action and isinstance(action["attributes"], list):
                    class_allowed_attrs = allowed_attributes.get(class_name, set())
                    for attr_item in action["attributes"]:
                        if isinstance(attr_item, dict) and isinstance(attr_item.get("name"), str):
                            if attr_item["name"].strip().casefold() not in class_allowed_attrs:
                                allowed = False
                                break
                targets.append((class_name, None))
            elif kind in {"RENAME_CLASS", "DELETE_CLASS"}:
                current_name = class_names.get(action.get("class_id", ""))
                targets.append((current_name, action.get("class_id")))
                allowed = current_name in allowed_classes and (
                    kind != "RENAME_CLASS"
                    or action.get("name", "").strip().casefold() in allowed_classes
                )
            elif kind == "CREATE_ATTRIBUTE":
                class_name = class_names.get(action.get("class_id", ""))
                targets.append((class_name, action.get("class_id")))
                allowed = (
                    class_name in allowed_classes
                    and action.get("name", "").strip().casefold()
                    in allowed_attributes.get(class_name or "", set())
                )
            elif kind in {"UPDATE_ATTRIBUTE", "REPOSITION_ATTRIBUTE", "DELETE_ATTRIBUTE"}:
                attribute = attributes_by_id.get(action.get("attribute_id", ""))
                class_name = class_names.get(str(attribute.class_id)) if attribute else None
                targets.append((class_name, str(attribute.class_id) if attribute else None))
                requested_name = action.get("name", attribute.name if attribute else "")
                allowed = (
                    attribute is not None
                    and class_name in allowed_classes
                    and requested_name.strip().casefold()
                    in allowed_attributes.get(class_name or "", set())
                )
            elif kind == "CREATE_RELATION":
                source_name = class_names.get(action.get("source_class_id", ""))
                target_name = class_names.get(action.get("target_class_id", ""))
                targets.extend(
                    [(source_name, action.get("source_class_id")), (target_name, action.get("target_class_id"))]
                )
                allowed = _relation_action_is_visible(
                    action, source_name, target_name, relations
                )
            else:
                relation = relations_by_id.get(action.get("relation_id", ""))
                source_name = class_names.get(str(relation.source_class_id)) if relation else None
                target_name = class_names.get(str(relation.target_class_id)) if relation else None
                if relation is not None:
                    targets.extend(
                        [(source_name, str(relation.source_class_id)), (target_name, str(relation.target_class_id))]
                    )
                allowed = relation is not None and _relation_action_is_visible(
                    {
                        **action,
                        "relation_type": relation.relation_type,
                        "source_cardinality": relation.source_cardinality,
                        "target_cardinality": relation.target_cardinality,
                        "name": relation.name,
                    },
                    source_name,
                    target_name,
                    relations,
                )
            if not allowed:
                raise AgentToolArgumentsException(
                    "La acción propuesta excede el alcance confirmado de la imagen."
                )
            for class_name, target_id in targets:
                matches = classes_by_name.get(class_name or "", [])
                selected_id = selected_class_ids.get(class_name)
                if selected_id is not None:
                    if selected_id not in {str(item.id) for item in matches} or (
                        target_id is not None and target_id != selected_id
                    ):
                        raise AgentToolArgumentsException(
                            "La acción no corresponde a la clase elegida por el usuario."
                        )
                elif len(matches) > 1:
                    raise AgentAmbiguousClassException(
                        matches[0].name,
                        [str(item.id) for item in matches],
                    )

    async def apply_diagram_changes(
        self,
        arguments: dict[str, Any],
        report: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        return await self._apply_actions(arguments, report, {})

    async def apply_scoped_diagram_changes(
        self,
        arguments: dict[str, Any],
        report: ProgressReporter | None,
        visual_scope: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._apply_actions(
            arguments, report, visual_scope.get("selected_class_ids", {})
        )

    async def _apply_actions(
        self,
        arguments: dict[str, Any],
        report: ProgressReporter | None,
        selected_class_ids: dict[str, str],
    ) -> dict[str, Any]:
        actions = validate_actions(arguments)
        results: list[dict[str, Any]] = []
        mutation_applied = False
        if hasattr(self, "class_tools"):
            self.class_tools.batch_reserved_positions.clear()
        if hasattr(self, "relation_tools"):
            self.relation_tools.batch_handle_usage.clear()

        for action in actions:
            kind = action.get("kind")
            if kind == "CREATE_CLASS" and hasattr(self, "class_tools"):
                for other_act in actions:
                    if other_act.get("kind") == "CREATE_RELATION":
                        for key in ("source_class_id", "target_class_id"):
                            raw_id = other_act.get(key)
                            if isinstance(raw_id, str):
                                try:
                                    cand_uuid = UUID(raw_id)
                                    exists = self.class_tools.session.exec(
                                        select(DiagramClassModel).where(
                                            DiagramClassModel.id == cand_uuid,
                                            DiagramClassModel.project_id == self.class_tools.project_id,
                                            DiagramClassModel.deleted_date.is_(None),
                                        )
                                    ).first()
                                    if exists is not None:
                                        action["_reference_class_id"] = cand_uuid
                                        break
                                except (ValueError, TypeError):
                                    pass
                    if "_reference_class_id" in action:
                        break

            async def report_for_action(event: dict[str, Any]) -> None:
                if report is None:
                    return
                payload = dict(event)
                target_name = action.get("name")
                if isinstance(target_name, str) and target_name.strip():
                    payload.setdefault("target_name", target_name.strip())
                await report(payload)

            action_report = report_for_action if report is not None else None
            try:
                result = await self._apply_one(action, action_report, selected_class_ids)
            except AgentMessagePersistenceException:
                raise
            except DomainException as exc:
                error_code = _stable_error_code(exc)
                term_failure = map_to_terminal_tool_failure(
                    exc=exc,
                    task_id="",
                    tool_name="apply_diagram_changes",
                    raw_target_name=action.get("name"),
                )
                result = {
                    "operation_id": action["operation_id"],
                    "status": "rejected",
                    "entity_refs": [],
                    "derived_effects": [],
                    "error_code": error_code,
                }
                if term_failure is not None:
                    result["terminal_failure"] = term_failure
                await _report_failure(action_report, action, result)
            except Exception:
                # Un problema de commit puede ocurrir después de que la BD lo haya
                # confirmado. Detenemos el lote y no disparamos un reintento ciego.
                result = {
                    "operation_id": action["operation_id"],
                    "status": "uncertain",
                    "entity_refs": [],
                    "derived_effects": [],
                    "error_code": "uncertain_result",
                }
                await _report_failure(action_report, action, result)
            result.setdefault("operation_id", action["operation_id"])
            results.append(result)
            mutation_applied = mutation_applied or result["status"] == "applied"
            if result["status"] != "applied":
                return {
                    "status": result["status"],
                    "results": results,
                    "stopped_at": action["operation_id"],
                    "mutation_applied": mutation_applied,
                }
        return {
            "status": "applied",
            "results": results,
            "mutation_applied": mutation_applied,
        }

    async def _apply_one(
        self,
        action: dict[str, Any],
        report: ProgressReporter | None,
        selected_class_ids: dict[str, str],
    ) -> dict[str, Any]:
        kind = action["kind"]
        if kind in {"CREATE_CLASS", "RENAME_CLASS", "DELETE_CLASS"}:
            selected_id = (
                selected_class_ids.get(action.get("name", "").strip().casefold())
                if kind == "CREATE_CLASS"
                else None
            )
            result = await self.class_tools.apply(
                action, report, selected_class_id=selected_id
            )
        elif kind in {
            "CREATE_ATTRIBUTE",
            "UPDATE_ATTRIBUTE",
            "REPOSITION_ATTRIBUTE",
            "DELETE_ATTRIBUTE",
        }:
            result = await self.attribute_tools.apply(action, report)
        else:
            result = await self.relation_tools.apply(action, report)
        return {
            "operation_id": action["operation_id"],
            **result,
        }


def _stable_error_code(error: DomainException) -> str:
    if getattr(error, "error_code", None):
        return getattr(error, "error_code")
    code = getattr(error, "code", "")
    if any(issue.value == str(code).lower() for issue in RelationValidationIssueCode):
        return str(code).lower()
    if isinstance(error, NotFoundException) or "NOT_FOUND" in code:
        return "not_found"
    if isinstance(error, ForbiddenException) or error.__class__.__name__ == "ProjectNotFoundException":
        return "forbidden"
    if isinstance(error, ConflictException):
        return "conflict"
    return "invalid_arguments"


async def _report_failure(
    report: ProgressReporter | None,
    action: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if report is None:
        return
    await report(
        {
            "operation_id": action["operation_id"],
            "action_kind": action["kind"],
            "status": result["status"],
            "entity_refs": result["entity_refs"],
            "derived_effects": result["derived_effects"],
            "error_code": result["error_code"],
        }
    )


def _relation_action_is_visible(
    action: dict[str, Any],
    source_name: str | None,
    target_name: str | None,
    visible_relations: list[Any],
) -> bool:
    if source_name is None or target_name is None:
        return False
    action_type = action.get("relation_type", "")
    action_name = action.get("name")
    action_sc = action.get("source_cardinality")
    action_tc = action.get("target_cardinality")

    for relation in visible_relations:
        if not isinstance(relation, dict):
            continue
        rel_src = relation.get("source")
        rel_tgt = relation.get("target")
        if not isinstance(rel_src, str) or not isinstance(rel_tgt, str):
            continue
        rel_type = relation.get("relation_type", "")
        rel_name = relation.get("name")
        rel_sc = relation.get("source_cardinality")
        rel_tc = relation.get("target_cardinality")

        check_name1 = action_name if (isinstance(rel_name, str) and rel_name.strip()) else None
        check_name2 = rel_name if (isinstance(rel_name, str) and rel_name.strip()) else None

        if are_relations_equivalent(
            type1=action_type,
            source1=source_name,
            target1=target_name,
            source_card1=action_sc,
            target_card1=action_tc,
            name1=check_name1,
            type2=rel_type,
            source2=rel_src,
            target2=rel_tgt,
            source_card2=rel_sc,
            target_card2=rel_tc,
            name2=check_name2,
        ):
            return True
    return False
