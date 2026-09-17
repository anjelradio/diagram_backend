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

    @staticmethod
    def _is_colliding(
        x: float,
        y: float,
        existing_classes: list[PlannedClass],
        safety_margin_x: float = 340.0,
        safety_margin_y: float = 230.0,
    ) -> bool:
        for c in existing_classes:
            if abs(x - c.position_x) < safety_margin_x and abs(y - c.position_y) < safety_margin_y:
                return True
        return False

    def _find_smart_position(
        self,
        class_name: str,
        raw_x: Any,
        raw_y: Any,
        all_actions: list[AiAction],
        classes_by_name: dict[str, PlannedClass],
    ) -> tuple[float, float]:
        step_x = 380.0
        step_y = 270.0
        origin_x = 160.0
        origin_y = 120.0
        existing_list = list(classes_by_name.values())

        # Si el AI proveyó coordenadas explícitas válidas
        if raw_x is not None and raw_y is not None:
            try:
                px = float(raw_x)
                py = float(raw_y)
                if math.isfinite(px) and math.isfinite(py):
                    if not self._is_colliding(px, py, existing_list):
                        return px, py
            except (ValueError, TypeError):
                pass

        if not existing_list:
            return origin_x, origin_y

        # 1. Buscar si esta clase tiene relación con alguna clase existente
        ref_class: PlannedClass | None = None
        for act in all_actions:
            act_p = act.payload or {}
            if act.type == AgentActionType.CREATE_RELATION:
                src = str(act_p.get("source_class_name", "")).strip().lower()
                tgt = str(act_p.get("target_class_name", "")).strip().lower()
                cur = class_name.lower()
                if src == cur and tgt in classes_by_name:
                    ref_class = classes_by_name[tgt]
                    break
                elif tgt == cur and src in classes_by_name:
                    ref_class = classes_by_name[src]
                    break
            elif act.type == AgentActionType.MOVE_CLASS:
                c_name = str(act_p.get("class_name", "")).strip().lower()
                ref_name = str(act_p.get("reference_class_name", "")).strip().lower()
                if c_name == class_name.lower() and ref_name in classes_by_name:
                    ref_class = classes_by_name[ref_name]
                    break

        if ref_class is not None:
            # Buscar en anillos concéntricos alrededor de la clase de referencia
            rx, ry = ref_class.position_x, ref_class.position_y
            candidate_offsets = [
                (step_x, 0.0),       # DERECHA
                (0.0, step_y),       # ABAJO
                (-step_x, 0.0),      # IZQUIERDA
                (0.0, -step_y),      # ARRIBA
                (step_x, step_y),    # ABAJO DERECHA
                (-step_x, step_y),   # ABAJO IZQUIERDA
                (step_x, -step_y),   # ARRIBA DERECHA
                (-step_x, -step_y),  # ARRIBA IZQUIERDA
                (step_x * 2, 0.0),
                (0.0, step_y * 2),
                (-step_x * 2, 0.0),
                (0.0, -step_y * 2),
            ]
            for dx, dy in candidate_offsets:
                cx = rx + dx
                cy = ry + dy
                if cx >= 60.0 and cy >= 60.0 and not self._is_colliding(cx, cy, existing_list):
                    return cx, cy

        # 2. Si no hay relación directa, posicionar cerca de la conglomeración (cluster)
        center_x = sum(c.position_x for c in existing_list) / len(existing_list)
        center_y = sum(c.position_y for c in existing_list) / len(existing_list)

        # Generar candidatos en cuadrícula y ordenar por distancia al centroide
        best_candidate = None
        best_dist = float("inf")

        min_gx = min(c.position_x for c in existing_list)
        max_gx = max(c.position_x for c in existing_list)
        min_gy = min(c.position_y for c in existing_list)
        max_gy = max(c.position_y for c in existing_list)

        start_col = max(0, int(min_gx // step_x) - 1)
        end_col = int(max_gx // step_x) + 2
        start_row = max(0, int(min_gy // step_y) - 1)
        end_row = int(max_gy // step_y) + 2

        for col in range(start_col, end_col + 2):
            for row in range(start_row, end_row + 2):
                cx = origin_x + col * step_x
                cy = origin_y + row * step_y
                if cx < 60.0 or cy < 60.0:
                    continue
                if not self._is_colliding(cx, cy, existing_list):
                    dist = (cx - center_x) ** 2 + (cy - center_y) ** 2
                    if dist < best_dist:
                        best_dist = dist
                        best_candidate = (cx, cy)

        if best_candidate is not None:
            return best_candidate

        # Fallback de emergencia
        total = len(existing_list)
        return origin_x + (total % 4) * step_x, origin_y + (total // 4) * step_y

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

                # Posición inteligente con prevención de colisiones y proximidad semántica
                raw_x = raw_payload.get("position_x")
                raw_y = raw_payload.get("position_y")
                pos_x, pos_y = self._find_smart_position(
                    class_name=name,
                    raw_x=raw_x,
                    raw_y=raw_y,
                    all_actions=ai_actions,
                    classes_by_name=classes_by_name,
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

            elif ai_action.type == AgentActionType.MOVE_CLASS:
                class_name = str(raw_payload.get("class_name", "")).strip()
                if not class_name:
                    raise AgentActionValidationException("El nombre de la clase a mover no puede estar vacío.")
                target_pc = classes_by_name.get(class_name.lower())
                if target_pc is None:
                    raise AgentActionValidationException(
                        f"No se encontró la clase '{class_name}' para mover."
                    )
                # Resolver destino: prioridad position_x/y explícitos, luego referencia+dirección, luego zona
                ref_name = str(raw_payload.get("reference_class_name", "")).strip() if raw_payload.get("reference_class_name") else None
                direction = str(raw_payload.get("direction", "")).strip().upper() if raw_payload.get("direction") else None
                zone = str(raw_payload.get("zone", "")).strip().lower() if raw_payload.get("zone") else None
                raw_x = raw_payload.get("position_x")
                raw_y = raw_payload.get("position_y")
                new_x: float | None = None
                new_y: float | None = None
                if raw_x is not None and raw_y is not None:
                    try:
                        new_x = float(raw_x)
                        new_y = float(raw_y)
                        if not math.isfinite(new_x) or not math.isfinite(new_y):
                            raise AgentActionValidationException(
                                "La posición propuesta para mover la clase no es un número finito."
                            )
                    except (TypeError, ValueError):
                        raise AgentActionValidationException(
                            "La posición propuesta para mover la clase no es válida."
                        )
                else:
                    # Resolver por referencia o zona
                    if ref_name:
                        ref_pc = classes_by_name.get(ref_name.lower())
                        if ref_name and ref_pc is None:
                            raise AgentActionValidationException(
                                f"No se encontró la clase de referencia '{ref_name}' para mover '{class_name}'."
                            )
                        # dirección por defecto RIGHT si no se especifica
                        dir_norm = direction or "RIGHT"
                        offset = 280.0
                        if dir_norm == "RIGHT":
                            new_x = ref_pc.position_x + offset
                            new_y = ref_pc.position_y
                        elif dir_norm == "LEFT":
                            new_x = ref_pc.position_x - offset
                            new_y = ref_pc.position_y
                        elif dir_norm == "TOP":
                            new_x = ref_pc.position_x
                            new_y = ref_pc.position_y - 240.0
                        elif dir_norm == "BOTTOM":
                            new_x = ref_pc.position_x
                            new_y = ref_pc.position_y + 240.0
                        elif dir_norm in ("NEAR", "CLOSE", "CERCA"):
                            new_x = ref_pc.position_x + 180.0
                            new_y = ref_pc.position_y + 60.0
                        else:
                            new_x = ref_pc.position_x + offset
                            new_y = ref_pc.position_y
                    elif zone:
                        zone_map = {
                            "center": (600.0, 400.0),
                            "centro": (600.0, 400.0),
                            "top-left": (150.0, 100.0),
                            "top-right": (1050.0, 100.0),
                            "bottom-left": (150.0, 700.0),
                            "bottom-right": (1050.0, 700.0),
                        }
                        if zone in zone_map:
                            new_x, new_y = zone_map[zone]
                        else:
                            new_x, new_y = zone_map["center"]
                    elif direction:
                        # dirección sin referencia: mover relativo a posición actual
                        step = 120.0
                        if direction == "RIGHT":
                            new_x = target_pc.position_x + step
                            new_y = target_pc.position_y
                        elif direction == "LEFT":
                            new_x = target_pc.position_x - step
                            new_y = target_pc.position_y
                        elif direction == "TOP":
                            new_x = target_pc.position_x
                            new_y = target_pc.position_y - step
                        elif direction == "BOTTOM":
                            new_x = target_pc.position_x
                            new_y = target_pc.position_y + step
                        else:
                            new_x = target_pc.position_x + step
                            new_y = target_pc.position_y
                    else:
                        raise AgentActionValidationException(
                            f"No se pudo determinar el destino para mover la clase '{class_name}'. Indique dirección, referencia o zona."
                        )
                # Validar finitos y aplicar fallback no colisionante simple
                assert new_x is not None and new_y is not None
                if not math.isfinite(new_x) or not math.isfinite(new_y):
                    raise AgentActionValidationException(
                        "La posición calculada para mover la clase no es válida."
                    )
                # Evitar superposición total: si otra clase ya ocupa exactamente esa posición, desplazar levemente
                for other in classes_by_name.values():
                    if other.id != target_pc.id and abs(other.position_x - new_x) < 5 and abs(other.position_y - new_y) < 5:
                        new_x += 30.0
                        new_y += 30.0
                        break
                target_pc.position_x = new_x
                target_pc.position_y = new_y
                payload = {
                    "class_id": target_pc.id,
                    "user_id": user_id,
                    "position_x": new_x,
                    "position_y": new_y,
                }
                validated_actions.append(
                    ValidatedAction(
                        action_type=AgentActionType.MOVE_CLASS,
                        payload=payload,
                        summary=f"Clase '{target_pc.name}' movida a ({new_x:.0f}, {new_y:.0f})",
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
