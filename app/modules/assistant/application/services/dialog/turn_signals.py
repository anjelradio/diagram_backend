"""Extracción de señales deterministas puras para el análisis de turnos conversacionales (Capa 0).

Operaciones en memoria, deterministas, sin I/O ni llamadas a red, con tiempo de ejecución < 1 ms.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

# Tokens de afirmación normalizados (sin tildes, minúsculas)
_CONFIRM_TOKENS = (
    "si",
    "ok",
    "okay",
    "dale",
    "hazlo",
    "procede",
    "adelante",
    "vale",
    "claro",
    "perfecto",
    "de acuerdo",
    "confirmo",
    "me parece bien",
    "por supuesto",
    "correcto",
    "por defecto",
    "la tipica",
    "la estandar",
    "lo recomendado",
    "la normal",
    "el tipico",
    "el estandar",
    "lo sugerido",
    "la sugerida",
)

# Tokens de cancelación / declinación
_DECLINE_TOKENS = (
    "no",
    "cancela",
    "cancelar",
    "olvidalo",
    "olvidate",
    "ninguna",
    "dejarlo",
    "dejalo",
    "para nada",
    "ya no",
)

# Patrones de abandono explícito aislado del hilo ("olvídate de eso", "cancela eso")
_ABANDON_PATTERN = re.compile(
    r"^(?:olv[ií]da(?:te)?(?:\s+de\s+(?:eso|ello|est[oe]|lo\s+anterior))?|"
    r"cancela(?:\s+(?:eso|ello|est[oe]|la\s+solicitud|lo\s+anterior))?|"
    r"dej[eé]moslo\s+(?:as[ií]|ah[ií])|d[eé]jalo\s+(?:as[ií]|ah[ií])|"
    r"ya\s+no\s+(?:hagas\s+nada|quiero\s+eso)|no\s+hagas\s+nada)[.!]?$",
    re.IGNORECASE,
)

# Patrón para dividir cláusulas compuestas:
# Ej: "sí, continúa y además crea la clase Árbol", "dale y crea una clase X", "olvídate de eso y mejor crea una clase Y"
_CLAUSE_SPLITTER = re.compile(
    r"(?:[,.;]\s*|\s+)(?:y\s+)?(?:adem[aá]s|luego|despu[eé]s|tambi[eé]n)\s*[:,]?\s+|"
    r"(?:[,.;]\s*|\s+(?:y|pero)\s+(?:mejor\s+|ahora\s+)?|(?:\s+en\s+vez\s+de\s+eso\s+|\s+en\s+lugar\s+de\s+eso\s+))"
    r"(?=(?:crea(?:r)?|haz|agrega(?:r)?|a[ñn]ade(?:r)?|anade(?:r)?|agrea(?:r)?|relaciona(?:r)?|conecta(?:r)?)\b)",
    re.IGNORECASE,
)

_RETRY_TOKENS = (
    "reintenta",
    "reintentar",
    "continua",
    "continúa",
    "sigue",
    "reanuda",
    "reanudar",
    "intenta de nuevo",
)


def normalize_text(text: str) -> str:
    """Normaliza quitando acentos, espacios superfluos y convirtiendo a minúsculas."""
    clean = text.strip()
    norm = "".join(
        c for c in unicodedata.normalize("NFD", clean.lower())
        if unicodedata.category(c) != "Mn"
    )
    return norm


@dataclass(frozen=True, slots=True)
class TurnSignals:
    """Conjunto de señales deterministas detectadas en el texto del usuario."""

    raw_text: str
    normalized_text: str
    primary_clause: str
    secondary_clauses: tuple[str, ...]
    is_affirmative: bool
    is_decline: bool
    is_explicit_abandon: bool
    is_retry: bool
    is_short: bool
    has_anaphora: bool
    option_label: str | None
    is_fk_request: bool = False
    is_pk_request: bool = False
    target_class_hint: str | None = None
    related_class_hint: str | None = None


_FK_INTENT_PATTERN = re.compile(
    r"\b(?:(?:llave|clave)[s]?\s+for[aá]nea[s]?|foreign\s+key[s]?|fk[s]?)\b",
    re.IGNORECASE,
)
_PK_INTENT_PATTERN = re.compile(
    r"\b(?:(?:llave|clave)[s]?\s+primaria[s]?|primary\s+key[s]?|pk[s]?)\b",
    re.IGNORECASE,
)

_SINGLE_ATTR_PATTERN = re.compile(
    r"\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|inserta(?:r)?|haz|pon(?:er)?)\s+"
    r"(?:(?:un|el|la)\s+)?(?:(?:atributo|campo|propiedad|columna)\s+)?"
    r"[`'\"]?([a-zA-Z0-9_]+)[`'\"]?",
    re.IGNORECASE,
)


def _extract_single_attribute_candidate(prompt: str) -> str | None:
    """Extrae el nombre de un atributo si el prompt pide crear o agregar un único atributo."""
    clean = prompt.strip()
    match = _SINGLE_ATTR_PATTERN.search(clean)
    if not match:
        return None
    cand = match.group(1).strip()
    stop_words = {
        "una", "un", "el", "la", "clase", "tabla", "nodo", "nuevo", "nueva",
        "relacion", "relación", "asociacion", "asociación", "conexion", "conexión",
    }
    if cand.casefold() in stop_words:
        return None
    # Si hay listas de múltiples atributos separados por comas o 'y', no es aislado
    remainder = clean[match.end():]
    if re.search(r"^\s*,\s*\w+", remainder) or re.search(r"^\s+y\s+(?:el\s+)?(?:atributo\s+)?\w+", remainder, re.IGNORECASE):
        return None
    return cand


def extract_class_hints_from_key_request(prompt: str) -> tuple[str | None, str | None]:
    """Extrae la clase sobre la que se pide la llave y la posible clase relacionada."""
    from app.modules.assistant.domain.dialog.key_attribute_rules import (
        extract_referenced_entity_from_fk,
        is_foreign_key_name,
    )

    clean = prompt.strip()
    target_match = re.search(
        r"\b(?:en|a|sobre|para)\s+(?:la\s+clase\s+|el\s+nodo\s+|la\s+tabla\s+)?`?([^\W\d]\w*)`?",
        clean,
        re.IGNORECASE,
    )
    target_class = None
    stop_words = {"la", "el", "una", "un", "llave", "foreign", "fk", "pk", "clase", "tabla", "este", "esta", "mi", "tu"}
    if target_match:
        cand = target_match.group(1).strip()
        if cand.casefold() not in stop_words:
            target_class = cand

    related_match = re.search(
        r"\b(?:con|hacia|referenciando\s+a|vinculada\s+a)\s+(?:la\s+clase\s+|la\s+tabla\s+)?`?([^\W\d]\w*)`?",
        clean,
        re.IGNORECASE,
    )
    related_class = None
    if related_match:
        cand = related_match.group(1).strip()
        if cand.casefold() not in stop_words:
            related_class = cand

    if related_class is None:
        cand_attr = _extract_single_attribute_candidate(clean)
        if cand_attr and is_foreign_key_name(cand_attr, target_class):
            ref = extract_referenced_entity_from_fk(cand_attr)
            if ref:
                related_class = ref.capitalize()

    return target_class, related_class


def is_isolated_fk_request(prompt: str) -> bool:
    """Detecta si el mensaje pide explícitamente crear una llave foránea aislada."""
    from app.modules.assistant.domain.dialog.key_attribute_rules import is_foreign_key_name

    clean = prompt.strip()
    norm = normalize_text(clean)
    if re.search(r"\bcrea(?:r)?\s+(?:una\s+)?clase\b", norm):
        return False

    if _FK_INTENT_PATTERN.search(clean):
        return True

    # Detectar también peticiones que piden crear un atributo con nombre de FK
    cand_attr = _extract_single_attribute_candidate(clean)
    if cand_attr:
        target_cls, _ = extract_class_hints_from_key_request(clean)
        if is_foreign_key_name(cand_attr, target_cls):
            return True

    return False


def is_isolated_pk_request(prompt: str) -> bool:
    """Detecta si el mensaje pide explícitamente crear una llave primaria aislada."""
    from app.modules.assistant.domain.dialog.key_attribute_rules import is_primary_key_name

    clean = prompt.strip()
    norm = normalize_text(clean)
    if re.search(r"\bcrea(?:r)?\s+(?:una\s+)?clase\b", norm):
        return False

    if _PK_INTENT_PATTERN.search(clean):
        return True

    # Detectar también peticiones que piden crear un atributo con nombre de PK (id, uuid, etc.)
    cand_attr = _extract_single_attribute_candidate(clean)
    if cand_attr:
        target_cls, _ = extract_class_hints_from_key_request(clean)
        if is_primary_key_name(cand_attr, target_cls):
            return True

    return False


def extract_turn_signals(user_prompt: str) -> TurnSignals:
    """Extrae las señales deterministas de un mensaje del usuario."""
    clean = user_prompt.strip()
    norm = normalize_text(clean)

    # 1. División de cláusulas
    parts = [p.strip() for p in _CLAUSE_SPLITTER.split(clean) if p.strip()]
    if not parts:
        primary = clean
        secondaries: tuple[str, ...] = ()
    else:
        primary = parts[0]
        secondaries = tuple(parts[1:])

    norm_primary = normalize_text(primary)

    # 2. Detección de abandono explícito aislado
    is_abandon = bool(_ABANDON_PATTERN.match(clean)) and not secondaries

    # 3. Detección de afirmación
    # Revisar si empieza o coincide con tokens afirmativos
    words = norm_primary.split()
    first_word = words[0] if words else ""
    first_two = " ".join(words[:2]) if len(words) >= 2 else ""

    is_affirmative = (
        first_word in _CONFIRM_TOKENS
        or first_two in _CONFIRM_TOKENS
        or any(norm_primary.startswith(t) for t in _CONFIRM_TOKENS)
    )

    # 4. Detección de rechazo / decline
    is_correction = bool(re.search(r"^(?:no,\s*mejor|no\s+espera|en\s+vez\s+de)", norm_primary))
    has_mutation_secondary = any(
        re.search(r"\b(?:crea|haz|agrega|anade|añade|agrea|relaciona|conecta|modifica|elimina|borra)\b", s, re.IGNORECASE)
        for s in secondaries
    )
    is_decline = False
    if not is_correction and not has_mutation_secondary:
        if is_abandon or any(norm_primary == dt or norm_primary.startswith(f"{dt} ") for dt in _DECLINE_TOKENS):
            is_decline = True

    # 5. Detección de reintento
    is_retry = any(
        norm_primary == rt or norm_primary.startswith(f"{rt} ")
        for rt in ("reintenta", "reintentar", "continua", "sigue", "reanuda", "reanudar", "intenta de nuevo")
    ) or (is_affirmative and any(rt in norm_primary for rt in ("continua", "reintenta", "sigue", "reanuda")))

    # 6. Brevedad y anáforas
    is_short = len(words) <= 3
    has_anaphora = bool(
        re.search(r"\b(?:eso|esa|esos|esas|ello|esto|esta|el primero|la primera|ambos|ambas)\b", norm_primary)
    )

    # 7. Etiqueta de opción: "opción A", "la opción B", "opcion 1", "aplica la opción A", "dale, aplica la opción A"
    option_label = None
    opt_match = re.search(r"\b(?:opci[oó]n|alternativa)\s+([a-zA-Z0-9]+)\b", clean, re.IGNORECASE)
    if opt_match:
        option_label = opt_match.group(1).casefold()

    # 8. Peticiones aisladas de FK y PK
    is_fk = is_isolated_fk_request(clean)
    is_pk = is_isolated_pk_request(clean)
    target_hint, related_hint = (
        extract_class_hints_from_key_request(clean)
        if (is_fk or is_pk)
        else (None, None)
    )

    return TurnSignals(
        raw_text=clean,
        normalized_text=norm,
        primary_clause=primary,
        secondary_clauses=secondaries,
        is_affirmative=is_affirmative,
        is_decline=is_decline,
        is_explicit_abandon=is_abandon,
        is_retry=is_retry,
        is_short=is_short,
        has_anaphora=has_anaphora,
        option_label=option_label,
        is_fk_request=is_fk,
        is_pk_request=is_pk,
        target_class_hint=target_hint,
        related_class_hint=related_hint,
    )

