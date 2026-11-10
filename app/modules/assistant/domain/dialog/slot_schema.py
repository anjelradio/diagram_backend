"""Esquemas declarativos de slots por acción y normalizadores deterministas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SlotDefinition:
    key: str
    action: str
    critical: bool = True
    question: str = ""
    allowed_values: tuple[str, ...] | None = None
    description: str = ""


_RELATION_TYPE_SYNONYMS: dict[str, str] = {
    "herencia": "GENERALIZATION",
    "generalizacion": "GENERALIZATION",
    "generalización": "GENERALIZATION",
    "padre": "GENERALIZATION",
    "hija": "GENERALIZATION",
    "subclase": "GENERALIZATION",
    "superclase": "GENERALIZATION",
    "composicion": "COMPOSITION",
    "composición": "COMPOSITION",
    "compuesta": "COMPOSITION",
    "compuesto": "COMPOSITION",
    "agregacion": "AGGREGATION",
    "agregación": "AGGREGATION",
    "asociacion": "ASSOCIATION",
    "asociación": "ASSOCIATION",
    "realizacion": "REALIZATION",
    "realización": "REALIZATION",
    "dependencia": "DEPENDENCY",
}


def normalize_relation_type(val: str | None) -> str | None:
    if not val or not isinstance(val, str):
        return None
    cleaned = val.strip().lower()
    cleaned = "".join(
        c for c in unicodedata.normalize("NFD", cleaned)
        if unicodedata.category(c) != "Mn"
    )
    if cleaned.upper() in {"ASSOCIATION", "GENERALIZATION", "COMPOSITION", "AGGREGATION", "REALIZATION", "DEPENDENCY"}:
        return cleaned.upper()
    direct = _RELATION_TYPE_SYNONYMS.get(cleaned)
    if direct:
        return direct
    # Busca por tokens individuales si es una frase corta
    for token in cleaned.split():
        token_clean = token.strip(" ¡!.,:;()[]\"'")
        if token_clean.upper() in {"ASSOCIATION", "GENERALIZATION", "COMPOSITION", "AGGREGATION", "REALIZATION", "DEPENDENCY"}:
            return token_clean.upper()
        if token_clean in _RELATION_TYPE_SYNONYMS:
            return _RELATION_TYPE_SYNONYMS[token_clean]
    return None


def normalize_cardinality(val: str | None) -> str | None:
    if not val or not isinstance(val, str):
        return None
    c = val.strip().lower()
    if c in {"1..1", "1:1", "1", "un", "una", "uno"}:
        return "1"
    if c in {"0..1", "0 a 1", "0 o 1", "cero a uno", "cero o uno"}:
        return "0..1"
    if c in {"0..*", "0 a muchos", "cero a muchos", "muchos", "muchas", "*", "n", "m", "0..n", "0..m", "varios", "varias"}:
        return "0..*"
    if c in {"1..*", "1 a muchos", "uno a muchos", "1..n", "1..m"}:
        return "1..*"
    return val.strip()


_COMMON_TYPE_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^(?:uuid|.+_uuid|guid)$", re.IGNORECASE), "UUID"),
    (re.compile(r"^(?:id|.+_id)$", re.IGNORECASE), "INTEGER"),
    (re.compile(r"^(?:nombre|name|descripcion|description|email|correo|direccion|address|telefono|phone|texto|text|titulo|title|codigo|code|slug|url)$", re.IGNORECASE), "TEXT"),
    (re.compile(r"^(?:precio|price|total|monto|amount|saldo|balance|costo|cost|descuento|discount|subtotal|tarifa|rate|sueldo|salario)$", re.IGNORECASE), "DECIMAL"),
    (re.compile(r"^(?:cantidad|quantity|stock|edad|age|numero|number|orden|order|contador|count|posicion|position|año|year|mes|month|dia|day)$", re.IGNORECASE), "INTEGER"),
    (re.compile(r"^(?:activo|active|es_.+|is_.+|habilitado|enabled|tiene_.+|has_.+|borrado|deleted|verificado|verified)$", re.IGNORECASE), "BOOLEAN"),
    (re.compile(r"^(?:fecha|date|fecha_nacimiento|birth_date)$", re.IGNORECASE), "DATE"),
    (re.compile(r"^(?:creado_en|created_at|actualizado_en|updated_at|modificado_en|timestamp|hora|time)$", re.IGNORECASE), "TIMESTAMP"),
)


def infer_attribute_type(name: str | None) -> str:
    """Infiere el tipo de dato UML más probable según la convención del nombre."""
    if not name or not isinstance(name, str):
        return "TEXT"
    clean = name.strip()
    for pattern, data_type in _COMMON_TYPE_PATTERNS:
        if pattern.match(clean):
            return data_type
    return "TEXT"


class ActionSlotRegistry:
    """Catálogo canónico de requisitos por acción."""

    @staticmethod
    def get_relation_slots(
        *,
        source_class: str | None,
        target_class: str | None,
        relation_type: str | None,
        facts: dict[str, Any],
    ) -> list[SlotDefinition]:
        slots: list[SlotDefinition] = []

        if not source_class:
            slots.append(
                SlotDefinition(
                    key="relation.source_class",
                    action="CREATE_RELATION",
                    critical=True,
                    question="¿Cuál es la primera clase de la relación?",
                )
            )
        if not target_class:
            slots.append(
                SlotDefinition(
                    key="relation.target_class",
                    action="CREATE_RELATION",
                    critical=True,
                    question="¿Cuál es la segunda clase de la relación?",
                )
            )

        norm_type = normalize_relation_type(relation_type)
        if not norm_type:
            s_name = source_class or "la primera clase"
            t_name = target_class or "la segunda clase"
            slots.append(
                SlotDefinition(
                    key="relation.type",
                    action="CREATE_RELATION",
                    critical=True,
                    question=f"¿Qué tipo de relación deseas entre {s_name} y {t_name} (asociación, herencia, composición, agregación)?",
                    allowed_values=("ASSOCIATION", "GENERALIZATION", "COMPOSITION", "AGGREGATION", "REALIZATION", "DEPENDENCY"),
                )
            )
            return slots

        # Reglas por tipo específico
        if norm_type == "ASSOCIATION":
            cardinalities = ("1", "0..1", "0..*", "1..*")
            has_src = facts.get("relation.source_cardinality") in cardinalities
            has_tgt = facts.get("relation.target_cardinality") in cardinalities
            if not has_src and not has_tgt:
                s_name = source_class or "un extremo"
                t_name = target_class or "el otro extremo"
                slots.append(
                    SlotDefinition(
                        key="relation.endpoint_cardinalities",
                        action="CREATE_RELATION",
                        critical=True,
                        question=f"¿Cuáles son las cardinalidades en cada extremo entre {s_name} y {t_name} (por ejemplo 1 a muchos)?",
                    )
                )
            elif not has_src:
                s_name = source_class or "la primera clase"
                slots.append(
                    SlotDefinition(
                        key="relation.source_cardinality",
                        action="CREATE_RELATION",
                        critical=True,
                        question=f"¿Cuál es la cardinalidad en el extremo de {s_name}?",
                    )
                )
            elif not has_tgt:
                t_name = target_class or "la segunda clase"
                slots.append(
                    SlotDefinition(
                        key="relation.target_cardinality",
                        action="CREATE_RELATION",
                        critical=True,
                        question=f"¿Cuál es la cardinalidad en el extremo de {t_name}?",
                    )
                )
        elif norm_type == "GENERALIZATION":
            roles = ("relation.superclass", "relation.subclass")
            has_super, has_sub = (
                _matches_endpoint(facts.get(role), source_class, target_class)
                for role in roles
            )
            distinct = not _same_class(*(facts.get(role) for role in roles))
            if not (has_super and has_sub and distinct):
                s_name = source_class or "origen"
                t_name = target_class or "destino"
                if has_super:
                    slots.append(
                        SlotDefinition(
                            key="relation.subclass",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la clase hija (subclase) para la superclase {facts['relation.superclass']}?",
                        )
                    )
                elif has_sub:
                    slots.append(
                        SlotDefinition(
                            key="relation.superclass",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la superclase (padre) para la subclase {facts['relation.subclass']}?",
                        )
                    )
                else:
                    slots.append(
                        SlotDefinition(
                            key="relation.direction",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la clase padre (superclase) y cuál la clase hija entre {s_name} y {t_name}?",
                        )
                    )
        elif norm_type in ("COMPOSITION", "AGGREGATION"):
            roles = ("relation.whole", "relation.part")
            has_whole, has_part = (
                _matches_endpoint(facts.get(role), source_class, target_class)
                for role in roles
            )
            distinct = not _same_class(*(facts.get(role) for role in roles))
            if not (has_whole and has_part and distinct):
                s_name = source_class or "origen"
                t_name = target_class or "destino"
                if has_whole:
                    slots.append(
                        SlotDefinition(
                            key="relation.part",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la clase contenida (la parte) de {facts['relation.whole']}?",
                        )
                    )
                elif has_part:
                    slots.append(
                        SlotDefinition(
                            key="relation.whole",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la clase contenedora (el todo) de {facts['relation.part']}?",
                        )
                    )
                else:
                    slots.append(
                        SlotDefinition(
                            key="relation.direction",
                            action="CREATE_RELATION",
                            critical=True,
                            question=f"¿Cuál es la clase contenedora (el todo) y cuál la parte entre {s_name} y {t_name}?",
                        )
                    )

        elif norm_type in ("REALIZATION", "DEPENDENCY"):
            if norm_type == "REALIZATION":
                roles = ("relation.implementer", "relation.contract")
                question = f"¿Cuál clase implementa a cuál entre {source_class or 'la primera'} y {target_class or 'la segunda'}?"
            else:
                roles = ("relation.dependent", "relation.dependency")
                question = f"¿Cuál clase depende de cuál entre {source_class or 'la primera'} y {target_class or 'la segunda'}?"
            first, second = (facts.get(role) for role in roles)
            if not (
                _matches_endpoint(first, source_class, target_class)
                and _matches_endpoint(second, source_class, target_class)
                and not _same_class(first, second)
            ):
                slots.append(SlotDefinition(
                    key="relation.direction", action="CREATE_RELATION",
                    critical=True, question=question,
                ))

        return slots

    @staticmethod
    def get_attribute_slots(
        *,
        target_class: str | None,
        name: str | None,
    ) -> list[SlotDefinition]:
        slots: list[SlotDefinition] = []
        if not target_class:
            slots.append(
                SlotDefinition(
                    key="attribute.target_class",
                    action="CREATE_ATTRIBUTE",
                    critical=True,
                    question=f"¿En qué clase deseas agregar el atributo{f' `{name}`' if name else ''}?",
                )
            )
        if not name:
            slots.append(
                SlotDefinition(
                    key="attribute.name",
                    action="CREATE_ATTRIBUTE",
                    critical=True,
                    question="¿Cuál es el nombre del atributo?",
                )
            )
        return slots

    @staticmethod
    def get_class_slots(*, name: str | None) -> list[SlotDefinition]:
        slots: list[SlotDefinition] = []
        if not name or not str(name).strip():
            slots.append(
                SlotDefinition(
                    key="class.name",
                    action="CREATE_CLASS",
                    critical=True,
                    question="¿Cuál es el nombre de la clase que deseas crear?",
                )
            )
        return slots


def _same_class(first: Any, second: Any) -> bool:
    return isinstance(first, str) and isinstance(second, str) and first.casefold() == second.casefold()


def _matches_endpoint(value: Any, source: str | None, target: str | None) -> bool:
    return _same_class(value, source) or _same_class(value, target)
