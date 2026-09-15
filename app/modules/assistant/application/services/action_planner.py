from dataclasses import dataclass, field
import math
from typing import Any
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.providers.ai_provider import AiAction
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.exceptions import (
    AgentActionValidationException,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramSnapshotDto,
)
from app.modules.diagram.application.services.diagram_relation_materializer import (
    MaterializationStrategy,
    calculate_bridge_class_position,
    determine_materialization_plan,
    generate_bridge_class_name,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)


@dataclass
class PlannedClass:
    id: UUID
    name: str
    position_x: float
    position_y: float
    attributes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ValidatedAction:
    action_type: AgentActionType
    payload: dict[str, Any]
    summary: str


class ActionPlanner:
    """Valida, resuelve identificadores y estructura las acciones generadas por la IA."""

    def plan_actions(
        self,
        project_id: UUID,
        user_id: str,
        ai_actions: list[AiAction],
        snapshot: DiagramSnapshotDto,
    ) -> list[ValidatedAction]:
        # Clases conocidas en el diagrama: name.lower() -> PlannedClass
        classes_by_name: dict[str, PlannedClass] = {}
        classes_by_id: dict[UUID, PlannedClass] = {}

        for c in snapshot.classes:
            attrs = [
                {
                    "id": a.id,
                    "name": a.name,
                    "data_type": a.data_type,
                    "position": a.position,
                    "is_primary_key": a.is_primary_key,
                    "is_nullable": a.is_nullable,
                    "is_foreign_key": a.is_foreign_key,
                    "referenced_class_id": a.referenced_class_id,
                    "relation_id": a.relation_id,
                }
                for a in c.attributes
            ]
            pc = PlannedClass(
                id=c.id,
                name=c.name,
                position_x=c.position_x,
                position_y=c.position_y,
                attributes=attrs,
            )
            classes_by_name[c.name.lower()] = pc
            classes_by_id[c.id] = pc

        # Relaciones conocidas: (source_id, target_id) -> list of relations
        relations_lookup: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
        handle_usage: dict[tuple[UUID, DiagramRelationHandle], int] = {}
        for r in snapshot.relations:
            key = (r.source.class_id, r.target.class_id)
            relations_lookup.setdefault(key, []).append({
                "id": r.id,
                "name": r.name,
                "relation_type": r.relation_type,
            })
            handle_usage[(r.source.class_id, r.source.handle)] = handle_usage.get(
                (r.source.class_id, r.source.handle), 0
            ) + 1
            handle_usage[(r.target.class_id, r.target.handle)] = handle_usage.get(
                (r.target.class_id, r.target.handle), 0
            ) + 1

        validated_actions: list[ValidatedAction] = []
        created_classes_count = 0

        for ai_action in ai_actions:
            raw_payload = ai_action.payload or {}

            if ai_action.type == AgentActionType.CREATE_CLASS:
                name = str(raw_payload.get("name", "")).strip()
                if not name:
                    raise AgentActionValidationException("El nombre de la clase no puede estar vacío.")
                if name.lower() in classes_by_name:
                    raise AgentActionValidationException(
                        f"Ya existe una clase con el nombre '{name}' en el proyecto."
                    )

                class_id = uuid4()
                pk_id = uuid4()

                # Posición automática en cuadrícula
                total_classes = len(classes_by_name)
                col = total_classes % 4
                row = total_classes // 4
                raw_x = raw_payload.get("position_x")
                raw_y = raw_payload.get("position_y")
                pos_x = float(raw_x) if raw_x is not None else (120.0 + col * 280.0)
                pos_y = float(raw_y) if raw_y is not None else (100.0 + row * 240.0)
                if not math.isfinite(pos_x) or not math.isfinite(pos_y):
                    raise AgentActionValidationException(
                        "La posición propuesta para la clase no es un número finito."
                    )

                pk_attribute_name = "id"
                pk_attr = {
                    "id": pk_id,
                    "name": pk_attribute_name,
                    "data_type": DiagramAttributeDataType.UUID.value,
                    "position": 0,
                    "is_primary_key": True,
                    "is_nullable": False,
                    "is_foreign_key": False,
                }

                new_pc = PlannedClass(
                    id=class_id,
                    name=name,
                    position_x=pos_x,
                    position_y=pos_y,
                    attributes=[pk_attr],
                )
                classes_by_name[name.lower()] = new_pc
                classes_by_id[class_id] = new_pc
                created_classes_count += 1

                payload = {
                    "id": class_id,
                    "project_id": project_id,
                    "user_id": user_id,
                    "name": name,
                    "position_x": pos_x,
                    "position_y": pos_y,
                    "primary_attribute_id": pk_id,
                    "primary_attribute_name": pk_attribute_name,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.CREATE_CLASS,
                        payload=payload,
                        summary=f"Clase '{name}' creada con ID {class_id}",
                    )
                )

            elif ai_action.type == AgentActionType.DELETE_CLASS:
                name = str(raw_payload.get("class_name", "")).strip()
                target_pc = classes_by_name.get(name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{name}' para eliminar."
                    )

                del classes_by_name[name.lower()]
                classes_by_id.pop(target_pc.id, None)

                payload = {
                    "class_id": target_pc.id,
                    "user_id": user_id,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.DELETE_CLASS,
                        payload=payload,
                        summary=f"Clase '{name}' eliminada",
                    )
                )

            elif ai_action.type == AgentActionType.RENAME_CLASS:
                old_name = str(raw_payload.get("class_name", "")).strip()
                new_name = str(raw_payload.get("new_name", "")).strip()
                target_pc = classes_by_name.get(old_name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{old_name}' para renombrar."
                    )
                if not new_name:
                    raise AgentActionValidationException(
                        "El nuevo nombre de la clase no puede estar vacío."
                    )
                if new_name.lower() in classes_by_name and new_name.lower() != old_name.lower():
                    raise AgentActionValidationException(
                        f"Ya existe una clase con el nombre '{new_name}'."
                    )

                del classes_by_name[old_name.lower()]
                target_pc.name = new_name
                classes_by_name[new_name.lower()] = target_pc

                payload = {
                    "class_id": target_pc.id,
                    "user_id": user_id,
                    "new_name": new_name,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.RENAME_CLASS,
                        payload=payload,
                        summary=f"Clase '{old_name}' renombrada a '{new_name}'",
                    )
                )

            elif ai_action.type == AgentActionType.CREATE_ATTRIBUTE:
                class_name = str(raw_payload.get("class_name", "")).strip()
                attr_name = str(raw_payload.get("name", "")).strip()
                if not attr_name:
                    raise AgentActionValidationException("El nombre del atributo no puede estar vacío.")

                target_pc = classes_by_name.get(class_name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{class_name}' para agregar el atributo '{attr_name}'."
                    )

                raw_dtype = raw_payload.get("data_type")
                data_type_enum: DiagramAttributeDataType | None = None
                if raw_dtype:
                    try:
                        data_type_enum = DiagramAttributeDataType(str(raw_dtype).upper())
                    except ValueError:
                        data_type_enum = DiagramAttributeDataType.TEXT

                attr_id = uuid4()
                position = len(target_pc.attributes)  # siguiente posición (PK es 0)

                new_attr = {
                    "id": attr_id,
                    "name": attr_name,
                    "data_type": data_type_enum.value if data_type_enum else None,
                    "position": position,
                    "is_primary_key": False,
                    "is_nullable": True,
                    "is_foreign_key": False,
                }
                target_pc.attributes.append(new_attr)

                payload = {
                    "id": attr_id,
                    "class_id": target_pc.id,
                    "user_id": user_id,
                    "name": attr_name,
                    "position": position,
                    "data_type": data_type_enum,
                    "is_nullable": True,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.CREATE_ATTRIBUTE,
                        payload=payload,
                        summary=f"Atributo '{attr_name}' ({data_type_enum.value if data_type_enum else 'sin tipo'}) creado en '{target_pc.name}'",
                    )
                )

            elif ai_action.type == AgentActionType.UPDATE_ATTRIBUTE:
                class_name = str(raw_payload.get("class_name", "")).strip()
                attr_name = str(raw_payload.get("attribute_name", "")).strip()
                target_pc = classes_by_name.get(class_name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{class_name}' para actualizar el atributo."
                    )

                attr = next(
                    (a for a in target_pc.attributes if a["name"].lower() == attr_name.lower()),
                    None,
                )
                if attr is None:
                    raise AgentActionValidationException(
                        f"No se encontró el atributo '{attr_name}' en la clase '{class_name}'."
                    )
                if attr.get("is_primary_key"):
                    raise AgentActionValidationException(
                        "No se puede modificar la clave primaria directamente."
                    )
                if attr.get("is_foreign_key"):
                    raise AgentActionValidationException(
                        "No se puede modificar directamente un atributo de clave foránea."
                    )

                new_name = raw_payload.get("new_name")
                new_dtype_str = raw_payload.get("new_data_type")
                new_dtype: DiagramAttributeDataType | None = None
                if new_dtype_str:
                    try:
                        new_dtype = DiagramAttributeDataType(str(new_dtype_str).upper())
                    except ValueError:
                        pass
                is_nullable = raw_payload.get("is_nullable")

                if new_name:
                    attr["name"] = str(new_name).strip()
                if new_dtype:
                    attr["data_type"] = new_dtype.value
                if is_nullable is not None:
                    attr["is_nullable"] = bool(is_nullable)

                payload = {
                    "attribute_id": attr["id"],
                    "user_id": user_id,
                    "new_name": new_name,
                    "new_data_type": new_dtype,
                    "is_nullable": is_nullable,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.UPDATE_ATTRIBUTE,
                        payload=payload,
                        summary=f"Atributo '{attr_name}' de '{target_pc.name}' actualizado",
                    )
                )

            elif ai_action.type == AgentActionType.DELETE_ATTRIBUTE:
                class_name = str(raw_payload.get("class_name", "")).strip()
                attr_name = str(raw_payload.get("attribute_name", "")).strip()
                target_pc = classes_by_name.get(class_name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{class_name}' para eliminar el atributo."
                    )

                attr = next(
                    (a for a in target_pc.attributes if a["name"].lower() == attr_name.lower()),
                    None,
                )
                if attr is None:
                    raise AgentActionValidationException(
                        f"No se encontró el atributo '{attr_name}' en la clase '{class_name}'."
                    )
                if attr.get("is_primary_key"):
                    raise AgentActionValidationException(
                        "No se puede eliminar la clave primaria de una clase."
                    )
                if attr.get("is_foreign_key"):
                    raise AgentActionValidationException(
                        "No se puede eliminar un atributo que actúa como clave foránea."
                    )

                target_pc.attributes = [a for a in target_pc.attributes if a["id"] != attr["id"]]

                payload = {
                    "attribute_id": attr["id"],
                    "user_id": user_id,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.DELETE_ATTRIBUTE,
                        payload=payload,
                        summary=f"Atributo '{attr_name}' eliminado de '{target_pc.name}'",
                    )
                )

            elif ai_action.type == AgentActionType.CREATE_RELATION:
                src_name = str(raw_payload.get("source_class_name", "")).strip()
                tgt_name = str(raw_payload.get("target_class_name", "")).strip()
                rel_type_str = str(raw_payload.get("relation_type", "ASSOCIATION")).upper()

                src_pc = classes_by_name.get(src_name.lower())
                tgt_pc = classes_by_name.get(tgt_name.lower())
                if src_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase origen '{src_name}' para la relación."
                    )
                if tgt_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase destino '{tgt_name}' para la relación."
                    )
                if src_pc.id == tgt_pc.id:
                    raise AgentActionValidationException(
                        "Una relación no puede conectar una clase consigo misma."
                    )

                try:
                    rel_type = DiagramRelationType(rel_type_str)
                except ValueError:
                    rel_type = DiagramRelationType.ASSOCIATION

                rel_name = str(raw_payload.get("name", "")).strip()
                if rel_type == DiagramRelationType.ASSOCIATION and not rel_name:
                    rel_name = "Nueva relación"
                src_card_str = raw_payload.get("source_cardinality")
                tgt_card_str = raw_payload.get("target_cardinality")

                src_card: DiagramCardinality | None = None
                tgt_card: DiagramCardinality | None = None

                if rel_type == DiagramRelationType.ASSOCIATION:
                    src_card = (
                        DiagramCardinality(str(src_card_str))
                        if src_card_str
                        else DiagramCardinality.ZERO_OR_MORE
                    )
                    tgt_card = (
                        DiagramCardinality(str(tgt_card_str))
                        if tgt_card_str
                        else DiagramCardinality.EXACTLY_ONE
                    )

                relation_id = uuid4()
                src_handle = self._select_handle(
                    raw_payload.get("source_handle"),
                    source=src_pc,
                    target=tgt_pc,
                    usage=handle_usage,
                    source_side=True,
                )
                tgt_handle = self._select_handle(
                    raw_payload.get("target_handle"),
                    source=tgt_pc,
                    target=src_pc,
                    usage=handle_usage,
                    source_side=False,
                )

                # Calcular plan determinista de materialización
                plan = determine_materialization_plan(
                    relation_type=rel_type,
                    source_class_id=src_pc.id,
                    target_class_id=tgt_pc.id,
                    source_attributes_count=len(src_pc.attributes),
                    target_attributes_count=len(tgt_pc.attributes),
                    source_cardinality=src_card,
                    target_cardinality=tgt_card,
                )

                materialization: dict[str, Any] = {
                    "strategy": plan.strategy.value
                }

                if plan.strategy == MaterializationStrategy.FOREIGN_KEY:
                    rule = plan.foreign_key
                    assert rule is not None
                    rec_pc = src_pc if rule.receiving_class_id == src_pc.id else tgt_pc
                    ref_pc = tgt_pc if rule.receiving_class_id == src_pc.id else src_pc
                    fk_id = uuid4()
                    fk_name = f"{ref_pc.name.lower()}_id"
                    fk_pos = len(rec_pc.attributes)
                    fk_data = {
                        "id": str(fk_id),
                        "class_id": str(rule.receiving_class_id),
                        "name": fk_name,
                        "position": fk_pos,
                        "referenced_class_id": str(rule.referenced_class_id),
                        "relation_id": str(relation_id),
                        "is_nullable": rule.is_nullable,
                        "is_foreign_key": True,
                        "is_primary_key": False,
                        "data_type": DiagramAttributeDataType.UUID.value,
                    }
                    materialization["foreign_attributes"] = [fk_data]
                    rec_pc.attributes.append(fk_data)

                elif plan.strategy == MaterializationStrategy.SHARED_PRIMARY_KEY:
                    rule = plan.shared_primary_key
                    assert rule is not None
                    sub_pk = next((a for a in src_pc.attributes if a.get("is_primary_key")), None)
                    if sub_pk is None:
                        raise AgentActionValidationException(
                            f"La subclase '{src_pc.name}' no tiene una clave primaria identificable."
                        )
                    materialization["shared_primary_key"] = {
                        "class_id": str(rule.subclass_id),
                        "attribute_id": str(sub_pk["id"]),
                        "referenced_class_id": str(rule.superclass_id),
                        "relation_id": str(relation_id),
                    }
                    sub_pk["is_foreign_key"] = True
                    sub_pk["referenced_class_id"] = rule.superclass_id
                    sub_pk["relation_id"] = relation_id

                elif plan.strategy == MaterializationStrategy.BRIDGE_CLASS:
                    rule = plan.bridge_class
                    assert rule is not None
                    bridge_id = uuid4()
                    all_names = [p.name for p in classes_by_name.values()]
                    bridge_name = generate_bridge_class_name(src_pc.name, tgt_pc.name, all_names)
                    b_pos_x, b_pos_y = calculate_bridge_class_position(
                        src_pc.position_x, src_pc.position_y, tgt_pc.position_x, tgt_pc.position_y
                    )
                    pk_id = uuid4()
                    fk1_id = uuid4()
                    fk2_id = uuid4()

                    materialization["bridge_class"] = {
                        "id": str(bridge_id),
                        "name": bridge_name,
                        "position_x": b_pos_x,
                        "position_y": b_pos_y,
                        "handle": DiagramRelationHandle.TOP_CENTER.value,
                        "primary_attribute": {
                            "id": str(pk_id),
                            "name": "id",
                            "data_type": DiagramAttributeDataType.UUID.value,
                            "position": 0,
                            "is_primary_key": True,
                            "is_nullable": False,
                        },
                        "foreign_attributes": [
                            {
                                "id": str(fk1_id),
                                "class_id": str(bridge_id),
                                "name": f"{src_pc.name.lower()}_id",
                                "position": 1,
                                "referenced_class_id": str(rule.source_class_id),
                                "relation_id": str(relation_id),
                                "is_foreign_key": True,
                                "is_primary_key": False,
                                "is_nullable": False,
                                "data_type": DiagramAttributeDataType.UUID.value,
                            },
                            {
                                "id": str(fk2_id),
                                "class_id": str(bridge_id),
                                "name": f"{tgt_pc.name.lower()}_id",
                                "position": 2,
                                "referenced_class_id": str(rule.target_class_id),
                                "relation_id": str(relation_id),
                                "is_foreign_key": True,
                                "is_primary_key": False,
                                "is_nullable": False,
                                "data_type": DiagramAttributeDataType.UUID.value,
                            },
                        ],
                    }

                    # Registrar la clase puente en el planner
                    b_pc = PlannedClass(
                        id=bridge_id,
                        name=bridge_name,
                        position_x=b_pos_x,
                        position_y=b_pos_y,
                        attributes=[
                            materialization["bridge_class"]["primary_attribute"],
                            materialization["bridge_class"]["foreign_attributes"][0],
                            materialization["bridge_class"]["foreign_attributes"][1],
                        ],
                    )
                    classes_by_name[bridge_name.lower()] = b_pc
                    classes_by_id[bridge_id] = b_pc

                payload = {
                    "id": relation_id,
                    "project_id": project_id,
                    "user_id": user_id,
                    "name": rel_name,
                    "relation_type": rel_type,
                    "source_class_id": src_pc.id,
                    "target_class_id": tgt_pc.id,
                    "source_handle": src_handle,
                    "target_handle": tgt_handle,
                    "source_cardinality": src_card,
                    "target_cardinality": tgt_card,
                    "materialization": materialization,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.CREATE_RELATION,
                        payload=payload,
                        summary=f"Relación {rel_type.value} creada entre '{src_pc.name}' y '{tgt_pc.name}'",
                    )
                )

                handle_usage[(src_pc.id, src_handle)] = handle_usage.get(
                    (src_pc.id, src_handle), 0
                ) + 1
                handle_usage[(tgt_pc.id, tgt_handle)] = handle_usage.get(
                    (tgt_pc.id, tgt_handle), 0
                ) + 1

            elif ai_action.type == AgentActionType.DELETE_RELATION:
                src_name = str(raw_payload.get("source_class_name", "")).strip()
                tgt_name = str(raw_payload.get("target_class_name", "")).strip()
                src_pc = classes_by_name.get(src_name.lower())
                tgt_pc = classes_by_name.get(tgt_name.lower())
                if src_pc is None or tgt_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontraron las clases para la relación a eliminar: '{src_name}' y '{tgt_name}'."
                    )

                rels = relations_lookup.get((src_pc.id, tgt_pc.id)) or relations_lookup.get(
                    (tgt_pc.id, src_pc.id)
                )
                if not rels:
                    raise AgentActionValidationException(
                        f"No existe relación entre '{src_name}' y '{tgt_name}'."
                    )
                rel_to_delete = rels.pop(0)

                payload = {
                    "relation_id": rel_to_delete["id"],
                    "user_id": user_id,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.DELETE_RELATION,
                        payload=payload,
                        summary=f"Relación eliminada entre '{src_pc.name}' y '{tgt_pc.name}'",
                    )
                )

            elif ai_action.type == AgentActionType.RENAME_RELATION:
                src_name = str(raw_payload.get("source_class_name", "")).strip()
                tgt_name = str(raw_payload.get("target_class_name", "")).strip()
                new_rel_name = str(raw_payload.get("new_name", "")).strip()
                src_pc = classes_by_name.get(src_name.lower())
                tgt_pc = classes_by_name.get(tgt_name.lower())
                if src_pc is None or tgt_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontraron las clases para la relación a renombrar: '{src_name}' y '{tgt_name}'."
                    )

                rels = relations_lookup.get((src_pc.id, tgt_pc.id)) or relations_lookup.get(
                    (tgt_pc.id, src_pc.id)
                )
                if not rels:
                    raise AgentActionValidationException(
                        f"No existe relación entre '{src_name}' y '{tgt_name}'."
                    )
                rel_to_rename = rels[0]

                payload = {
                    "relation_id": rel_to_rename["id"],
                    "user_id": user_id,
                    "new_name": new_rel_name,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.RENAME_RELATION,
                        payload=payload,
                        summary=f"Relación entre '{src_pc.name}' y '{tgt_pc.name}' renombrada a '{new_rel_name}'",
                    )
                )

        return validated_actions

    @staticmethod
    def _select_handle(
        proposed: Any,
        *,
        source: PlannedClass,
        target: PlannedClass,
        usage: dict[tuple[UUID, DiagramRelationHandle], int],
        source_side: bool,
    ) -> DiagramRelationHandle:
        """Acepta el handle de la IA y usa el lado orientado menos congestionado si no es válido."""
        if proposed is not None:
            try:
                candidate = DiagramRelationHandle(str(proposed).upper())
                # Se permite compartir un handle, pero una propuesta con dos
                # o más relaciones ya resulta congestionada: buscamos una
                # alternativa con menor ocupación antes de aceptarla.
                if usage.get((source.id, candidate), 0) < 2:
                    return candidate
            except ValueError:
                pass

        dx = target.position_x - source.position_x
        dy = target.position_y - source.position_y
        if abs(dx) >= abs(dy):
            sides = (
                (DiagramRelationHandle.RIGHT_CENTER, DiagramRelationHandle.LEFT_CENTER)
                if dx >= 0
                else (DiagramRelationHandle.LEFT_CENTER, DiagramRelationHandle.RIGHT_CENTER)
            )
        else:
            sides = (
                (DiagramRelationHandle.BOTTOM_CENTER, DiagramRelationHandle.TOP_CENTER)
                if dy >= 0
                else (DiagramRelationHandle.TOP_CENTER, DiagramRelationHandle.BOTTOM_CENTER)
            )
        # Cada llamada recibe el centro de la clase que tendrá el handle y el
        # centro de su contraparte; por eso el primer lado siempre apunta al destino.
        preferred = sides[0]
        candidates = [preferred] + [h for h in DiagramRelationHandle if h != preferred]
        return min(candidates, key=lambda handle: usage.get((source.id, handle), 0))
