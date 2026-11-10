"""Contratos estrictos para las diez acciones de Diagram permitidas al agente."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    is_valid_cardinality,
    normalize_cardinality,
    validate_relation_request,
)
from app.modules.assistant.domain.exceptions import (
    AgentToolArgumentsException,
    UnsupportedAgentToolActionException,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType

MAX_ACTIONS = settings.AGENT_MAX_DIAGRAM_ACTIONS
MAX_OPERATION_ID_LENGTH = 100

_ACTION_PROPERTIES: dict[str, set[str]] = {
    "CREATE_CLASS": {"operation_id", "kind", "name", "position", "attributes"},
    "RENAME_CLASS": {"operation_id", "kind", "class_id", "name"},
    "DELETE_CLASS": {"operation_id", "kind", "class_id"},
    "CREATE_ATTRIBUTE": {
        "operation_id", "kind", "class_id", "name", "data_type", "nullable", "position"
    },
    "UPDATE_ATTRIBUTE": {
        "operation_id", "kind", "attribute_id", "name", "data_type", "nullable"
    },
    "REPOSITION_ATTRIBUTE": {"operation_id", "kind", "attribute_id", "position"},
    "DELETE_ATTRIBUTE": {"operation_id", "kind", "attribute_id"},
    "CREATE_RELATION": {
        "operation_id",
        "kind",
        "relation_type",
        "source_class_id",
        "target_class_id",
        "source_handle",
        "target_handle",
        "source_cardinality",
        "target_cardinality",
        "name",
    },
    "RENAME_RELATION": {"operation_id", "kind", "relation_id", "name"},
    "DELETE_RELATION": {"operation_id", "kind", "relation_id"},
}

DIAGRAM_MUTATION_TOOL = AiToolDefinition(
    name="apply_diagram_changes",
    description=(
        "Ejecuta una lista ordenada y acotada de cambios en el diagrama. Cada acción "
        "se confirma por separado; detente y revisa los resultados antes de continuar. "
        "Al crear una clase con CREATE_CLASS puedes incluir sus atributos en attributes: [{'name': '...'}]. "
        "Para añadir atributos o relaciones a clases ya existentes, reutiliza su class_id confirmado; "
        "nunca envíes null ni inventes IDs. "
        "No crees manualmente llaves primarias (se generan al crear la clase), llaves "
        "foráneas ni clases puente (se generan automáticamente al crear relaciones)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_ACTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "operation_id": {"type": "string", "minLength": 1, "maxLength": 100},
                        "kind": {"type": "string", "enum": sorted(_ACTION_PROPERTIES)},
                        "class_id": {"type": "string", "format": "uuid"},
                        "attribute_id": {"type": "string", "format": "uuid"},
                        "relation_id": {"type": "string", "format": "uuid"},
                        "source_class_id": {
                            "type": "string",
                            "format": "uuid",
                            "description": "ID de la clase origen. En GENERALIZATION (herencia) DEBE ser la subclase / clase hija (de donde parte la flecha). En COMPOSITION/AGGREGATION es el todo o contenedor.",
                        },
                        "target_class_id": {
                            "type": "string",
                            "format": "uuid",
                            "description": "ID de la clase destino. En GENERALIZATION (herencia) DEBE ser la superclase / clase padre (donde se dibuja el triángulo indicador de herencia). En COMPOSITION/AGGREGATION es la parte contenida.",
                        },
                        "name": {"type": "string", "minLength": 1, "maxLength": 255},
                        "position": {
                            "oneOf": [
                                {"type": "integer", "minimum": 1},
                                {
                                    "type": "object",
                                    "properties": {
                                        "x": {"type": "number", "minimum": -100000, "maximum": 100000},
                                        "y": {"type": "number", "minimum": -100000, "maximum": 100000},
                                    },
                                    "required": ["x", "y"],
                                    "additionalProperties": False,
                                },
                            ]
                        },
                        "data_type": {
                            "type": ["string", "null"],
                            "enum": [None, *(item.value for item in DiagramAttributeDataType)],
                        },
                        "nullable": {"type": "boolean"},
                        "attributes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                                    "data_type": {
                                        "type": ["string", "null"],
                                        "enum": [None, *(item.value for item in DiagramAttributeDataType)],
                                    },
                                    "nullable": {"type": "boolean"},
                                },
                                "required": ["name"],
                                "additionalProperties": False,
                            },
                        },
                        "relation_type": {"type": "string", "enum": [item.value for item in DiagramRelationType]},
                        "source_handle": {"type": "string", "enum": [item.value for item in DiagramRelationHandle]},
                        "target_handle": {"type": "string", "enum": [item.value for item in DiagramRelationHandle]},
                        "source_cardinality": {
                            "type": ["string", "null"],
                            "enum": [None, *(item.value for item in DiagramCardinality), "1..1"],
                            "description": "Cardinalidad situada en el extremo origen (source_class_id). Responde a: ¿cuántas instancias de origen corresponden a 1 de destino? En 1:N Padre(source)->Hijo(target) (ej. Cliente->Venta), source_cardinality es '1'. En N:1 Hijo(source)->Padre(target) (ej. Producto->Categoria), source_cardinality es '0..*' o '1..*'.",
                        },
                        "target_cardinality": {
                            "type": ["string", "null"],
                            "enum": [None, *(item.value for item in DiagramCardinality), "1..1"],
                            "description": "Cardinalidad situada en el extremo destino (target_class_id). Responde a: ¿cuántas instancias de destino corresponden a 1 de origen? En 1:N Padre(source)->Hijo(target) (ej. Cliente->Venta), target_cardinality es '0..*' o '1..*'. En N:1 Hijo(source)->Padre(target) (ej. Producto->Categoria), target_cardinality es '1'.",
                        },
                    },
                    "required": ["operation_id", "kind"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["actions"],
        "additionalProperties": False,
    },
)


_RELATION_KIND_NORMALIZATIONS: dict[str, str] = {
    rel.value.upper(): rel.value for rel in DiagramRelationType
}
_RELATION_KIND_NORMALIZATIONS.update({
    f"CREATE_{rel.value.upper()}": rel.value for rel in DiagramRelationType
})


def validate_actions(value: Any) -> list[dict[str, Any]]:
    """Valida límites y discriminadores antes de resolver o mutar entidades."""
    if not isinstance(value, dict) or set(value) != {"actions"}:
        raise AgentToolArgumentsException()
    actions = value["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise AgentToolArgumentsException()
    normalized: list[dict[str, Any]] = []
    operation_ids: set[str] = set()
    for i, raw_action in enumerate(actions):
        if not isinstance(raw_action, dict):
            raise AgentToolArgumentsException()
        action = dict(raw_action)
        kind = action.get("kind")
        if not isinstance(kind, str):
            raise AgentToolArgumentsException()

        # Resiliencia: auto-normalizar tipos de relación pasados erróneamente en 'kind'
        kind_clean = kind.strip().upper()
        if kind_clean in _RELATION_KIND_NORMALIZATIONS:
            action["relation_type"] = action.get("relation_type") or _RELATION_KIND_NORMALIZATIONS[kind_clean]
            kind = "CREATE_RELATION"
            action["kind"] = kind
        elif kind_clean == "CREATE_RELATION":
            kind = "CREATE_RELATION"
            action["kind"] = kind

        # Resiliencia: limpiar campos auxiliares de relación que el LLM a veces incluye
        if kind == "CREATE_RELATION":
            action.pop("head_class", None)
            if isinstance(action.get("relation_type"), str):
                action["relation_type"] = action["relation_type"].strip().upper()

        if kind not in _ACTION_PROPERTIES:
            raise UnsupportedAgentToolActionException()
        allowed = _ACTION_PROPERTIES[kind]

        # Resiliencia: auto-asignar operation_id si falta, es nulo o está vacío
        op_id = action.get("operation_id")
        if not isinstance(op_id, str) or not op_id.strip():
            op_id = f"op_{i + 1}"
            action["operation_id"] = op_id
        else:
            op_id = op_id.strip()
            if len(op_id) > MAX_OPERATION_ID_LENGTH or op_id in operation_ids:
                raise AgentToolArgumentsException()
        operation_ids.add(op_id)

        # Resiliencia: limpiar valores None en campos opcionales donde None no es válido
        if "attributes" in action and action["attributes"] is None:
            action.pop("attributes")
        if "position" in action and action["position"] is None:
            action.pop("position")

        # Limpiar claves extrañas con valor None enviadas por el LLM
        for extra_key in list(action.keys()):
            if extra_key not in allowed and action[extra_key] is None:
                action.pop(extra_key)

        if set(action) - allowed:
            raise AgentToolArgumentsException()

        _validate_action_fields(action)
        normalized.append(dict(action))
    return normalized


def _validate_action_fields(action: dict[str, Any]) -> None:
    kind = action["kind"]
    required_by_kind = {
        "CREATE_CLASS": (),
        "RENAME_CLASS": ("class_id", "name"),
        "DELETE_CLASS": ("class_id",),
        "CREATE_ATTRIBUTE": ("class_id", "name"),
        "UPDATE_ATTRIBUTE": ("attribute_id",),
        "REPOSITION_ATTRIBUTE": ("attribute_id", "position"),
        "DELETE_ATTRIBUTE": ("attribute_id",),
        "CREATE_RELATION": ("relation_type", "source_class_id", "target_class_id"),
        "RENAME_RELATION": ("relation_id", "name"),
        "DELETE_RELATION": ("relation_id",),
    }
    if any(key not in action for key in required_by_kind[kind]):
        raise AgentToolArgumentsException()
    if kind == "CREATE_CLASS" and "name" in action and not _valid_name(action["name"]):
        raise AgentToolArgumentsException()
    if kind == "CREATE_CLASS" and "attributes" in action:
        _validate_create_class_attributes(action["attributes"])
    if "name" in action and not _valid_name(action["name"]):
        raise AgentToolArgumentsException()
    if kind == "UPDATE_ATTRIBUTE" and not {"name", "data_type", "nullable"} & action.keys():
        raise AgentToolArgumentsException()
    if kind == "CREATE_ATTRIBUTE" and not _valid_data_type(action.get("data_type")):
        raise AgentToolArgumentsException()
    if kind == "UPDATE_ATTRIBUTE":
        if "data_type" in action and not _valid_data_type(action["data_type"]):
            raise AgentToolArgumentsException()
        if "nullable" in action and not isinstance(action["nullable"], bool):
            raise AgentToolArgumentsException()
    if kind == "CREATE_ATTRIBUTE" and "nullable" in action and not isinstance(action["nullable"], bool):
        raise AgentToolArgumentsException()
    if kind == "CREATE_CLASS" and "position" in action:
        _validate_xy_position(action["position"])
    if kind in {"CREATE_ATTRIBUTE", "REPOSITION_ATTRIBUTE"} and "position" in action:
        _positive_int(action["position"])
    for key in ("class_id", "attribute_id", "relation_id", "source_class_id", "target_class_id"):
        if key in action:
            _uuid(action[key])
    if kind == "CREATE_RELATION":
        if not isinstance(action["relation_type"], str) or action["relation_type"] not in {
            item.value for item in DiagramRelationType
        }:
            raise AgentToolArgumentsException()
        for key in ("source_handle", "target_handle"):
            if key in action and (
                not isinstance(action[key], str)
                or action[key] not in {item.value for item in DiagramRelationHandle}
            ):
                raise AgentToolArgumentsException()

        rel_type = action["relation_type"]
        src_card = action.get("source_cardinality")
        tgt_card = action.get("target_cardinality")

        try:
            if src_card is not None:
                src_card = normalize_cardinality(src_card)
                action["source_cardinality"] = src_card
            if tgt_card is not None:
                tgt_card = normalize_cardinality(tgt_card)
                action["target_cardinality"] = tgt_card
        except ValueError as exc:
            raise AgentToolArgumentsException() from exc

        issue = validate_relation_request(rel_type, src_card, tgt_card)
        if issue is not None:
            raise AgentToolArgumentsException()


def _validate_xy_position(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise AgentToolArgumentsException()
    for coordinate in value.values():
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or abs(coordinate) > 100_000:
            raise AgentToolArgumentsException()


def _positive_int(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AgentToolArgumentsException()


def _uuid(value: Any) -> UUID:
    if not isinstance(value, str):
        raise AgentToolArgumentsException()
    try:
        return UUID(value)
    except ValueError as exc:
        raise AgentToolArgumentsException() from exc


def _valid_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 255


def _valid_data_type(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and value in {item.value for item in DiagramAttributeDataType}
    )


def _valid_cardinality(value: Any) -> bool:
    return value is None or is_valid_cardinality(value)


def _validate_create_class_attributes(attributes: Any) -> None:
    if not isinstance(attributes, list):
        raise AgentToolArgumentsException()
    for attr in attributes:
        if not isinstance(attr, dict):
            raise AgentToolArgumentsException()
        if "nullable" in attr and attr["nullable"] is None:
            attr.pop("nullable")
        for extra_key in list(attr.keys()):
            if extra_key not in {"name", "data_type", "nullable"} and attr[extra_key] is None:
                attr.pop(extra_key)
        if set(attr) - {"name", "data_type", "nullable"}:
            raise AgentToolArgumentsException()
        if "name" not in attr or not _valid_name(attr["name"]):
            raise AgentToolArgumentsException()
        if "data_type" in attr and not _valid_data_type(attr["data_type"]):
            raise AgentToolArgumentsException()
        if "nullable" in attr and not isinstance(attr["nullable"], bool):
            raise AgentToolArgumentsException()


