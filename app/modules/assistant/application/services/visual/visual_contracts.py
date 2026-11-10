"""Contratos de aplicación para interpretar imágenes de diagramas UML/ERD."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    is_association,
    is_structural,
    normalize_cardinality,
)
from app.modules.assistant.domain.exceptions import AiProviderError
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType

VisualMode = Literal["mutate", "analyze", "clarify"]
RequestedVisualMode = Literal["mutate", "analyze"]
DiagramKind = Literal["UML_CLASS", "ERD", "OTHER", "UNKNOWN"]

MAX_VISUAL_JSON_CHARS = 24_000
MAX_VISUAL_ITEMS = 100
MAX_VISUAL_TEXT_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class VisualIntent:
    mode: VisualMode
    needs_image: bool
    visual_request: str
    scope: dict[str, Any]
    independent_tasks: tuple[str, ...] = ()
    clarification: str | None = None
    requested_mode: RequestedVisualMode | None = None

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "needs_image": self.needs_image,
            "visual_request": self.visual_request,
            "scope": self.scope,
            "independent_tasks": list(self.independent_tasks),
            "clarification": self.clarification,
            "requested_mode": self.requested_mode,
        }


@dataclass(frozen=True, slots=True)
class VisualEvidence:
    supported: bool
    diagram_kind: DiagramKind
    classes: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    uncertainties: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "supported": self.supported,
                "diagram_kind": self.diagram_kind,
                "classes": list(self.classes),
                "relations": list(self.relations),
                "uncertainties": list(self.uncertainties),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def parse_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > MAX_VISUAL_JSON_CHARS:
        raise AiProviderError()
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError) as exc:
        raise AiProviderError() from exc
    if not isinstance(value, dict):
        raise AiProviderError()
    return value


def parse_visual_intent(raw: str) -> VisualIntent:
    value = parse_json_object(raw)
    allowed = {
        "mode", "needs_image", "visual_request", "scope", "independent_tasks",
        "clarification", "requested_mode",
    }
    if set(value) - allowed:
        raise AiProviderError()
    mode = value.get("mode")
    needs_image = value.get("needs_image")
    visual_request = value.get("visual_request", "")
    scope = value.get("scope", {})
    independent_tasks = value.get("independent_tasks", [])
    clarification = value.get("clarification")
    requested_mode = value.get("requested_mode")
    if (
        not isinstance(mode, str)
        or mode not in {"mutate", "analyze", "clarify"}
        or not isinstance(needs_image, bool)
        or not isinstance(visual_request, str)
        or len(visual_request) > MAX_VISUAL_TEXT_CHARS
        or not isinstance(scope, dict)
        or not isinstance(independent_tasks, list)
        or len(independent_tasks) > MAX_VISUAL_ITEMS
        or not all(isinstance(item, str) and len(item) <= MAX_VISUAL_TEXT_CHARS for item in independent_tasks)
        or (clarification is not None and (not isinstance(clarification, str) or len(clarification) > 500))
        or (mode == "clarify" and not clarification)
        or (
            requested_mode is not None
            and (
                not isinstance(requested_mode, str)
                or requested_mode not in {"mutate", "analyze"}
            )
        )
        or (mode != "clarify" and requested_mode is not None)
        or (mode != "clarify" and needs_image and not visual_request)
    ):
        raise AiProviderError()
    # Algunos modelos devuelven el selector de clases directamente en scope.
    # Normalizar esa forma evita descartar una intención válida sin relajar
    # la validación de los selectores ni de sus categorías.
    if set(scope) <= {"include", "exclude"} and scope:
        scope = {"classes": scope}
    _validate_scope(scope)
    return VisualIntent(
        mode=mode,
        needs_image=needs_image,
        visual_request=visual_request,
        scope=scope,
        independent_tasks=tuple(independent_tasks),
        clarification=clarification,
        requested_mode=requested_mode,
    )


def parse_visual_evidence(raw: str) -> VisualEvidence:
    value = parse_json_object(raw)
    allowed = {"supported", "diagram_kind", "classes", "relations", "uncertainties"}
    if set(value) - allowed:
        raise AiProviderError()
    supported = value.get("supported")
    diagram_kind = value.get("diagram_kind")
    classes = value.get("classes", [])
    relations = value.get("relations", [])
    uncertainties = value.get("uncertainties", [])
    if (
        not isinstance(supported, bool)
        or not isinstance(diagram_kind, str)
        or diagram_kind not in {"UML_CLASS", "ERD", "OTHER", "UNKNOWN"}
        or not isinstance(classes, list)
        or not isinstance(relations, list)
        or not isinstance(uncertainties, list)
        or len(classes) > MAX_VISUAL_ITEMS
        or len(relations) > MAX_VISUAL_ITEMS
        or len(uncertainties) > MAX_VISUAL_ITEMS
        or not all(isinstance(item, dict) for item in [*classes, *relations])
        or not all(isinstance(item, str) and len(item) <= MAX_VISUAL_TEXT_CHARS for item in uncertainties)
    ):
        raise AiProviderError()
    # Limit nested payloads as well; provider output is untrusted.
    if any(len(json.dumps(item, ensure_ascii=False)) > 4_000 for item in [*classes, *relations]):
        raise AiProviderError()
    uncertainties_list = list(uncertainties)
    visual_class_names: set[str] = set()
    for class_item in classes:
        # El modelo visual puede traducir esta única clave aun cuando el
        # contrato pida JSON en inglés. Conservar los datos antes de validar.
        if "atributos" in class_item and "attributes" not in class_item:
            class_item["attributes"] = class_item.pop("atributos")
        if set(class_item) - {"name", "attributes", "description"}:
            raise AiProviderError()
        name = class_item.get("name")
        attributes = class_item.get("attributes", [])
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 255
            or not isinstance(attributes, list)
            or len(attributes) > MAX_VISUAL_ITEMS
            or not all(isinstance(attribute, dict) for attribute in attributes)
        ):
            raise AiProviderError()
        folded_name = name.strip().casefold()
        if folded_name in visual_class_names:
            uncertainties_list.append(
                f"La imagen contiene varias clases llamadas `{name}`; indica cuál corresponde."
            )
        visual_class_names.add(folded_name)
        for attribute in attributes:
            if set(attribute) - {
                "name", "data_type", "key_kind", "nullable", "description"
            }:
                raise AiProviderError()
            attribute_name = attribute.get("name")
            data_type = attribute.get("data_type")
            key_kind = attribute.get("key_kind", "uncertain")
            nullable = attribute.get("nullable")
            if (
                not isinstance(attribute_name, str)
                or not attribute_name.strip()
                or len(attribute_name) > 255
                or not isinstance(key_kind, str)
                or key_kind not in {"ordinary", "primary_key", "foreign_key", "uncertain"}
                or (nullable is not None and not isinstance(nullable, bool))
            ):
                raise AiProviderError()
            if data_type is not None:
                canonical_type = _canonical_data_type(data_type)
                if canonical_type is None:
                    uncertainties_list.append(
                        f"El tipo del atributo `{attribute_name}` ({data_type}) no pertenece a los tipos admitidos; pide precisión."
                    )
                    attribute["data_type"] = None
                else:
                    attribute["data_type"] = canonical_type
            attribute["key_kind"] = key_kind
    for relation in relations:
        if set(relation) - {
            "name", "source", "target", "relation_type", "source_cardinality",
            "target_cardinality", "head_class", "description",
        }:
            raise AiProviderError()
        if (
            not isinstance(relation.get("source"), str)
            or not relation.get("source", "").strip()
            or not isinstance(relation.get("target"), str)
            or not relation.get("target", "").strip()
        ):
            uncertainties_list.append("No se pudieron identificar con certeza los extremos de una relación.")
        relation_type = relation.get("relation_type")
        if relation_type is not None and (
            not isinstance(relation_type, str)
            or relation_type not in {item.value for item in DiagramRelationType}
        ):
            uncertainties_list.append("No se pudo asignar el tipo de una relación a los tipos admitidos.")

        head_class = relation.get("head_class")
        if head_class is not None and not isinstance(head_class, str):
            raise AiProviderError()
        if isinstance(head_class, str):
            head_class = head_class.strip()
            relation["head_class"] = head_class or None
        else:
            relation["head_class"] = None

        if is_structural(relation_type):
            if not relation.get("head_class"):
                uncertainties_list.append(
                    "No se pudo leer con certeza la dirección o cabeza de la relación estructural."
                )
            if relation.get("source_cardinality") is not None or relation.get("target_cardinality") is not None:
                uncertainties_list.append(
                    "Las relaciones estructurales no deben tener cardinalidad en el diagrama."
                )
        elif is_association(relation_type):
            if relation.get("head_class") is not None:
                uncertainties_list.append("Las asociaciones no admiten cabeza estructural.")
            for cardinality_key in ("source_cardinality", "target_cardinality"):
                cardinality = relation.get(cardinality_key)
                if cardinality is not None:
                    try:
                        relation[cardinality_key] = normalize_cardinality(cardinality)
                    except ValueError:
                        uncertainties_list.append("No se pudo leer con certeza la cardinalidad de una relación.")
            if relation.get("source_cardinality") is None or relation.get("target_cardinality") is None:
                uncertainties_list.append(
                    "Falta una cardinalidad necesaria para establecer la relación de asociación."
                )
        else:
            for cardinality_key in ("source_cardinality", "target_cardinality"):
                cardinality = relation.get(cardinality_key)
                if cardinality is not None and (
                    not isinstance(cardinality, str)
                    or cardinality not in {item.value for item in DiagramCardinality} | {"1..1"}
                ):
                    uncertainties_list.append("No se pudo leer con certeza la cardinalidad de una relación.")
    return VisualEvidence(
        supported=supported and diagram_kind in {"UML_CLASS", "ERD"},
        diagram_kind=diagram_kind,
        classes=tuple(classes),
        relations=tuple(relations),
        uncertainties=tuple(dict.fromkeys(uncertainties_list)),
    )


def _validate_scope(scope: dict[str, Any]) -> None:
    """Acepta solo selectores conocidos; nunca interpreta texto arbitrario."""
    if set(scope) - {"classes", "attributes", "relations"}:
        raise AiProviderError()
    for selector in scope.values():
        if isinstance(selector, str) and selector in {"all", "none"}:
            continue
        if isinstance(selector, list) and len(selector) <= MAX_VISUAL_ITEMS and all(
            isinstance(item, str) and 0 < len(item.strip()) <= 255 for item in selector
        ):
            continue
        if isinstance(selector, dict) and set(selector) <= {"include", "exclude"}:
            if selector and all(
                value in {"all", "none"}
                if isinstance(value, str)
                else isinstance(value, list)
                and len(value) <= MAX_VISUAL_ITEMS
                and all(isinstance(item, str) and 0 < len(item.strip()) <= 255 for item in value)
                for value in selector.values()
            ):
                continue
        raise AiProviderError()


def _canonical_data_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    canonical = value.strip().upper()
    aliases = {
        "STRING": "TEXT",
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "INT": "INTEGER",
        "BIGINT": "INTEGER",
        "SMALLINT": "INTEGER",
        "FLOAT": "DECIMAL",
        "NUMERIC": "DECIMAL",
        "BOOL": "BOOLEAN",
        "DATETIME": "TIMESTAMP",
    }
    canonical = aliases.get(canonical, canonical)
    supported = {item.value for item in DiagramAttributeDataType}
    return canonical if canonical in supported else None


def restrict_visual_intent_to_pending(
    intent: VisualIntent, pending_payload: Any
) -> VisualIntent | None:
    """Reduce una intención retomada a los permisos del mensaje aclarado."""
    if not isinstance(pending_payload, dict):
        return None
    previous = pending_payload.get("intent")
    requested_mode = pending_payload.get("requested_mode")
    if (
        not isinstance(previous, dict)
        or not isinstance(requested_mode, str)
        or requested_mode not in {"mutate", "analyze"}
        or intent.mode == "clarify"
        or intent.mode != requested_mode
    ):
        return None
    previous_scope = previous.get("scope", {})
    if not isinstance(previous_scope, dict):
        return None
    scope: dict[str, Any] = {}
    for key in {"classes", "attributes", "relations"}:
        if key not in previous_scope:
            if key in intent.scope:
                scope[key] = intent.scope[key]
            continue
        scope[key] = _intersect_selector(
            previous_scope[key], intent.scope.get(key, "all")
        )
    previous_tasks = previous.get("independent_tasks", [])
    if not isinstance(previous_tasks, list) or not all(
        isinstance(task, str) for task in previous_tasks
    ):
        return None
    return VisualIntent(
        mode=intent.mode,
        needs_image=intent.needs_image,
        visual_request=(
            previous.get("visual_request")
            if isinstance(previous.get("visual_request"), str)
            and previous.get("visual_request")
            else intent.visual_request
        ),
        scope=scope,
        independent_tasks=tuple(previous_tasks),
        clarification=intent.clarification,
        requested_mode=None,
    )


def _intersect_selector(left: Any, right: Any) -> Any:
    if left is None or left == "all":
        return right
    if right is None or right == "all":
        return left
    if left == "none" or right == "none":
        return "none"
    if isinstance(left, list) and isinstance(right, list):
        right_set = {item.casefold() for item in right}
        return [item for item in left if item.casefold() in right_set]
    if isinstance(left, list):
        return [item for item in left if _selector_contains(right, item)]
    if isinstance(right, list):
        return [item for item in right if _selector_contains(left, item)]
    if isinstance(left, dict) or isinstance(right, dict):
        left_include = left.get("include", "all") if isinstance(left, dict) else left
        right_include = right.get("include", "all") if isinstance(right, dict) else right
        left_exclude = left.get("exclude", "none") if isinstance(left, dict) else "none"
        right_exclude = right.get("exclude", "none") if isinstance(right, dict) else "none"
        include = _intersect_selector(left_include, right_include)
        exclude = _union_selector(left_exclude, right_exclude)
        return {"include": include, "exclude": exclude}
    # Unknown selector shapes fail closed.
    return "none"


def _selector_contains(selector: Any, name: str) -> bool:
    if selector is None or selector == "all":
        return True
    if selector == "none":
        return False
    if isinstance(selector, list):
        return name.casefold() in {item.casefold() for item in selector}
    if isinstance(selector, dict):
        return _selector_contains(selector.get("include", "all"), name) and not _selector_contains(
            selector.get("exclude", "none"), name
        )
    return False


def _union_selector(left: Any, right: Any) -> Any:
    if left == "all" or right == "all":
        return "all"
    if left == "none":
        return right
    if right == "none":
        return left
    if isinstance(left, list) and isinstance(right, list):
        seen: set[str] = set()
        merged = []
        for item in (*left, *right):
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged
    return "all"
