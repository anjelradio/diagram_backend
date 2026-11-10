"""Política canónica para la interpretación y validación de relaciones del asistente."""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType


class RelationValidationIssueCode(str, Enum):
    """Códigos estables de error de validación para intenciones de relaciones."""

    RELATION_CARDINALITY_REQUIRED = "relation_cardinality_required"
    RELATION_CARDINALITY_FORBIDDEN = "relation_cardinality_forbidden"
    RELATION_DIRECTION_REQUIRED = "relation_direction_required"
    RELATION_CLASS_AMBIGUOUS = "relation_class_ambiguous"
    RELATION_COMBINATION_INVALID = "relation_combination_invalid"
    RELATION_ALREADY_MATERIALIZED = "relation_already_materialized"


CANONICAL_CARDINALITIES: tuple[str, ...] = ("1", "0..1", "0..*", "1..*")

CARDINALITY_ALIASES: dict[str, str] = {
    "1..1": "1",
}


def _coerce_relation_type(
    relation_type: DiagramRelationType | str,
) -> DiagramRelationType | None:
    """Coacciona una cadena o miembro enum a DiagramRelationType si es válido."""
    if isinstance(relation_type, DiagramRelationType):
        return relation_type
    try:
        return DiagramRelationType(str(relation_type).upper())
    except (ValueError, KeyError, AttributeError):
        return None


def normalize_cardinality(val: str | None) -> str | None:
    """Normaliza una cadena de cardinalidad a su valor canónico o lanza ValueError."""
    if val is None:
        return None
    val_str = str(val).strip()
    aliased = CARDINALITY_ALIASES.get(val_str, val_str)
    if aliased not in CANONICAL_CARDINALITIES:
        raise ValueError(f"Invalid cardinality: {val}")
    return aliased


def is_valid_cardinality(val: str | None) -> bool:
    """Determina si una cardinalidad es válida y soportada (incluyendo alias permitidos)."""
    if val is None:
        return False
    try:
        normalize_cardinality(val)
        return True
    except ValueError:
        return False


def is_association(relation_type: DiagramRelationType | str) -> bool:
    """Determina si el tipo corresponde a una asociación."""
    rt = _coerce_relation_type(relation_type)
    return rt == DiagramRelationType.ASSOCIATION


def is_structural(relation_type: DiagramRelationType | str) -> bool:
    """Determina si el tipo corresponde a una relación estructural (no asociativa)."""
    rt = _coerce_relation_type(relation_type)
    if rt is None:
        return False
    return rt in {
        DiagramRelationType.AGGREGATION,
        DiagramRelationType.COMPOSITION,
        DiagramRelationType.GENERALIZATION,
        DiagramRelationType.REALIZATION,
        DiagramRelationType.DEPENDENCY,
    }


def validate_relation_request(
    relation_type: DiagramRelationType | str,
    source_cardinality: str | None,
    target_cardinality: str | None,
) -> RelationValidationIssueCode | None:
    """Valida la combinación de tipo de relación y cardinalidades.
    
    Retorna None si la solicitud es válida, o un código de problema si es inválida.
    """
    if is_association(relation_type):
        if source_cardinality is None or target_cardinality is None:
            return RelationValidationIssueCode.RELATION_CARDINALITY_REQUIRED
        if not is_valid_cardinality(source_cardinality) or not is_valid_cardinality(target_cardinality):
            return RelationValidationIssueCode.RELATION_COMBINATION_INVALID
        return None

    if is_structural(relation_type):
        if source_cardinality is not None or target_cardinality is not None:
            return RelationValidationIssueCode.RELATION_CARDINALITY_FORBIDDEN
        return None

    return RelationValidationIssueCode.RELATION_COMBINATION_INVALID


def get_head_placement(relation_type: DiagramRelationType | str) -> str | None:
    """Retorna 'source', 'target', o None según dónde se ubica la cabeza de la relación."""
    rt = _coerce_relation_type(relation_type)
    if rt in (DiagramRelationType.AGGREGATION, DiagramRelationType.COMPOSITION):
        return "source"
    if rt in (
        DiagramRelationType.GENERALIZATION,
        DiagramRelationType.REALIZATION,
        DiagramRelationType.DEPENDENCY,
    ):
        return "target"
    return None


def get_semantic_roles(relation_type: DiagramRelationType | str) -> tuple[str, str]:
    """Retorna las etiquetas semánticas canónicas para (source_role, target_role)."""
    rt = _coerce_relation_type(relation_type)
    if rt == DiagramRelationType.ASSOCIATION:
        return ("source_cardinality_endpoint", "target_cardinality_endpoint")
    if rt in (DiagramRelationType.AGGREGATION, DiagramRelationType.COMPOSITION):
        return ("whole", "part")
    if rt == DiagramRelationType.GENERALIZATION:
        return ("subclass", "superclass")
    if rt == DiagramRelationType.REALIZATION:
        return ("implementer", "contract")
    if rt == DiagramRelationType.DEPENDENCY:
        return ("dependent", "dependency")
    return ("source", "target")


def translate_head_to_endpoints(
    relation_type: DiagramRelationType | str,
    endpoint_a: str,
    endpoint_b: str,
    head_class: str,
) -> tuple[str, str]:
    """Traduce un head explícito y dos extremos a la tupla canónica (source_class, target_class)."""
    if is_association(relation_type) or not is_structural(relation_type):
        raise ValueError(RelationValidationIssueCode.RELATION_COMBINATION_INVALID.value)

    if head_class not in (endpoint_a, endpoint_b):
        raise ValueError(RelationValidationIssueCode.RELATION_DIRECTION_REQUIRED.value)

    other_class = endpoint_b if head_class == endpoint_a else endpoint_a
    placement = get_head_placement(relation_type)

    if placement == "source":
        return (head_class, other_class)
    else:
        return (other_class, head_class)


def are_relations_equivalent(
    type1: DiagramRelationType | str,
    source1: str,
    target1: str,
    source_card1: str | None,
    target_card1: str | None,
    name1: str | None,
    type2: DiagramRelationType | str,
    source2: str,
    target2: str,
    source_card2: str | None,
    target_card2: str | None,
    name2: str | None,
) -> bool:
    """Verifica si dos relaciones son semánticamente equivalentes (considerando simetría en asociaciones)."""
    rt1 = _coerce_relation_type(type1)
    rt2 = _coerce_relation_type(type2)
    if rt1 is None or rt2 is None or rt1 != rt2:
        return False

    n1 = (name1 or "").strip().casefold()
    n2 = (name2 or "").strip().casefold()
    if n1 != n2:
        return False

    s1, t1 = str(source1).strip().casefold(), str(target1).strip().casefold()
    s2, t2 = str(source2).strip().casefold(), str(target2).strip().casefold()

    # Normalizar cardinalidades si aplican
    sc1 = normalize_cardinality(source_card1) if source_card1 is not None else None
    tc1 = normalize_cardinality(target_card1) if target_card1 is not None else None
    sc2 = normalize_cardinality(source_card2) if source_card2 is not None else None
    tc2 = normalize_cardinality(target_card2) if target_card2 is not None else None

    if is_association(rt1):
        direct = (
            s1 == s2
            and t1 == t2
            and sc1 == sc2
            and tc1 == tc2
        )
        reversed_eq = (
            s1 == t2
            and t1 == s2
            and sc1 == tc2
            and tc1 == sc2
        )
        return direct or reversed_eq

    # Para relaciones estructurales, la dirección es estricta
    return s1 == s2 and t1 == t2
