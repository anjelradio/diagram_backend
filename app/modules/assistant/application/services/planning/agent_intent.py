"""Clasificación y representación temporal de la intención en lenguaje natural."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ActionKind = Literal["create", "update", "delete", "query", "clarify", "none"]
CertaintyLevel = Literal["high", "medium", "low", "ambiguous"]

_CREATE_PATTERNS = re.compile(
    r"\b(crea(?:r)?|haz(?:me)?|hacer|agrega(?:r)?|añade(?:r)?|genera(?:r)?|recrea(?:r)?|"
    r"create|add|make|generate)\b",
    re.IGNORECASE,
)
_UPDATE_PATTERNS = re.compile(
    r"\b(edita(?:r)?|modifica(?:r)?|actualiza(?:r)?|renombra(?:r)?|ajusta(?:r)?|"
    r"cambia(?:r)?\s+(?:el\s+)?nombre|edit|update|rename|modify|adjust)\b",
    re.IGNORECASE,
)
_DELETE_PATTERNS = re.compile(
    r"\b(elimina(?:r)?|borra(?:r)?|quita(?:r)?|remueve(?:r)?|suprime(?:r)?|"
    r"delete|remove)\b",
    re.IGNORECASE,
)
_RELATION_PATTERNS = re.compile(
    r"\b(relaci[oó]na(?:r|las|los)?|con[eé]cta(?:r|las|los)?|vinc[uú]la(?:r|las|los)?|"
    r"relate|connect)\b",
    re.IGNORECASE,
)
_ACTION_ON_RELATION_OR_ANAPHORA = re.compile(
    r"\b(?:aplica(?:r)?|aplíca(?:lo|la|los|las)?|implementa(?:r)?|implementa(?:lo|la|los|las)?|"
    r"establece(?:r)?|ejecuta(?:r)?|ejecúta(?:lo|la|los|las)?|procede\s+(?:con)?|"
    r"haz\s+(?:esa|ese|este|esta|el|la|los|las)?|hazlo|pon(?:er)?)\s+"
    r"(?:(?:con\s+)?(?:es[ae]s?|est[ae]s?|el|la|los|las)\s+)?(?:siguientes\s+)?"
    r"(?:generalizaci[oó]n(?:es)?|herencia(?:s)?|asociaci[oó]n(?:es)?|composici[oó]n(?:es)?|"
    r"agregaci[oó]n(?:es)?|dependencia(?:s)?|realizaci[oó]n(?:es)?|relaci[oó]n(?:es)?|"
    r"cambio(?:s)?|propuesta(?:s)?|sugerencia(?:s)?|recomendaci[oó]n(?:es)?|"
    r"lo\s+(?:propuesto|sugerido|hablado|mencionado|recomendado|anterior))\b",
    re.IGNORECASE,
)
_RELATION_CONFIGURATION_PATTERNS = re.compile(
    r"(?:\b(?:es|será|sera|sería|seria|será\s+una|se\s+trata\s+de)\s+"
    r"(?:una\s+)?relaci[oó]n\s+(?:de\s+)?"
    r"(?:herencia|generalizaci[oó]n|composici[oó]n|agregaci[oó]n|"
    r"realizaci[oó]n|dependencia|asociaci[oó]n)\b|"
    r"\b\w+\s+hereda\s+de\s+\w+\b|"
    r"\bclase\s+padre\b.+\bclase\s+hij[oa]\b)",
    re.IGNORECASE | re.DOTALL,
)
_REQUEST_SUBJUNCTIVE_CREATE = re.compile(
    r"\b(?:quiero|necesito|pido|solicito)\s+que\s+(?:me\s+)?(?:crees|haga(?:s)?)\b",
    re.IGNORECASE,
)
_REQUEST_SUBJUNCTIVE_RELATE = re.compile(
    r"\b(?:quiero|necesito|pido|solicito)\s+que\s+(?:me\s+)?relaciones\b",
    re.IGNORECASE,
)
_QUERY_PATTERNS = re.compile(
    r"\b(qué|dime|consulta(?:r)?|busca(?:r)?|explica(?:r)?|describe|describir|"
    r"revisa(?:r)?|cuál|cual|cuántas|cuantas|cuántos|cuantos|how|what|analyze|inspect|tell\s+me)\b",
    re.IGNORECASE,
)
_NEGATION_PATTERNS = re.compile(
    r"\b(no\s+(?:crees|creas|crear|hagas|hacer|borres|borrar|elimines|eliminar|"
    r"agregues|agregar|añadas|añadir|modifiques|modificar|actualices|actualizar|"
    r"quites|quitar|remuevas|remover|cambies|cambiar|relaciones|relacionar|toques|toque|nada))\b",
    re.IGNORECASE,
)
_HYPOTHETICAL_OR_DOUBT_PATTERNS = re.compile(
    r"\b(debería|deberia|podría|podria|sería\s+bueno|seria\s+bueno|se\s+puede|conviene)\b",
    re.IGNORECASE,
)
_CITED_EXAMPLE_PATTERNS = re.compile(
    r"\b(?:un\s+)?ejemplo\b[^:]*:|"
    r"\bpor\s+ejemplo\b|"
    r"\bcomo\s+ejemplo\b",
    re.IGNORECASE,
)
_AMBIGUOUS_PATTERNS = re.compile(
    r"\b(tal\s+vez|quizás|quizas|o\s+quizás|o\s+quizas|podríamos\s+ver|podriamos\s+ver|"
    r"hacer\s+algo\s+con|hacer\s+algo\s+en|ver\s+si\s+clase\s+o\s+atributo)\b",
    re.IGNORECASE,
)
_SEQUENCE_MARKERS = re.compile(
    r"\b(y\s+luego|después|despues|luego|además|ademas|then|after\s+that|also)\b",
    re.IGNORECASE,
)
_EXPLICIT_BATCH = re.compile(
    r"\b(?:clases|atributos|campos|relaciones)\s+"
    r"[\w`]+(?:\s*\([^)]*\))?(?:\s*,\s*[\w`]+(?:\s*\([^)]*\))?)*(?:\s+y\s+[\w`]+(?:\s*\([^)]*\))?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AgentIntent:
    action: ActionKind
    target: str
    scope: str | None
    certainty: CertaintyLevel
    requires_mutation: bool
    is_negated: bool = False
    is_question: bool = False
    is_ambiguous: bool = False
    raw_prompt: str = ""


def classify_agent_intent(prompt: str) -> AgentIntent:
    """Clasifica la intención del usuario a partir del texto de entrada."""
    cleaned = prompt.strip()
    if not cleaned:
        return AgentIntent(
            action="none",
            target="",
            scope=None,
            certainty="high",
            requires_mutation=False,
            raw_prompt=prompt,
        )

    # 1. Ejemplos citados (no autorizan mutación)
    if _CITED_EXAMPLE_PATTERNS.search(cleaned):
        return AgentIntent(
            action="none",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=False,
            raw_prompt=prompt,
        )

    # 2. Negaciones explícitas (no autorizan mutación)
    if _NEGATION_PATTERNS.search(cleaned):
        return AgentIntent(
            action="none",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=False,
            is_negated=True,
            raw_prompt=prompt,
        )

    # 3. Ambigüedades que impiden elegir una acción segura
    if _AMBIGUOUS_PATTERNS.search(cleaned):
        return AgentIntent(
            action="clarify",
            target=cleaned,
            scope=None,
            certainty="ambiguous",
            requires_mutation=False,
            is_ambiguous=True,
            raw_prompt=prompt,
        )

    # 4. Preguntas o dudas hipotéticas
    is_question = "?" in cleaned or "¿" in cleaned
    is_hypothetical = bool(_HYPOTHETICAL_OR_DOUBT_PATTERNS.search(cleaned))
    if is_hypothetical or (is_question and not _SEQUENCE_MARKERS.search(cleaned) and not has_direct_mutation_command(cleaned)):
        return AgentIntent(
            action="query",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=False,
            is_question=True,
            raw_prompt=prompt,
        )

    # 5. Detección de acciones de mutación
    has_create = bool(_CREATE_PATTERNS.search(cleaned) or _REQUEST_SUBJUNCTIVE_CREATE.search(cleaned))
    has_update = bool(_UPDATE_PATTERNS.search(cleaned))
    has_delete = bool(_DELETE_PATTERNS.search(cleaned))
    has_anaphora_action = bool(_ACTION_ON_RELATION_OR_ANAPHORA.search(cleaned))
    has_relation = bool(
        _RELATION_PATTERNS.search(cleaned)
        or _REQUEST_SUBJUNCTIVE_RELATE.search(cleaned)
        or _RELATION_CONFIGURATION_PATTERNS.search(cleaned)
        or has_anaphora_action
    )
    has_query = bool(_QUERY_PATTERNS.search(cleaned))

    if has_create or has_relation:
        return AgentIntent(
            action="create",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=True,
            raw_prompt=prompt,
        )

    if has_update:
        return AgentIntent(
            action="update",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=True,
            raw_prompt=prompt,
        )

    if has_delete:
        return AgentIntent(
            action="delete",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=True,
            raw_prompt=prompt,
        )

    if has_query:
        return AgentIntent(
            action="query",
            target=cleaned,
            scope=None,
            certainty="high",
            requires_mutation=False,
            is_question=is_question,
            raw_prompt=prompt,
        )

    # Por defecto, consulta o texto informativo si no coincide con mutaciones
    return AgentIntent(
        action="query" if is_question else "none",
        target=cleaned,
        scope=None,
        certainty="low",
        requires_mutation=False,
        is_question=is_question,
        raw_prompt=prompt,
    )


def has_direct_mutation_command(prompt: str) -> bool:
    """Determina si hay una orden de mutación imperativa explícita no negada."""
    if _NEGATION_PATTERNS.search(prompt) or _CITED_EXAMPLE_PATTERNS.search(prompt):
        return False
    return bool(
        _CREATE_PATTERNS.search(prompt)
        or _REQUEST_SUBJUNCTIVE_CREATE.search(prompt)
        or _UPDATE_PATTERNS.search(prompt)
        or _DELETE_PATTERNS.search(prompt)
        or _RELATION_PATTERNS.search(prompt)
        or _REQUEST_SUBJUNCTIVE_RELATE.search(prompt)
        or _ACTION_ON_RELATION_OR_ANAPHORA.search(prompt)
    )


def requires_mutation(prompt: str) -> bool:
    """Determina de forma unificada y segura si la solicitud requiere mutación."""
    intent = classify_agent_intent(prompt)
    return intent.requires_mutation


def requires_plan(prompt: str) -> bool:
    """Determina si una solicitud requiere plan compuesto o puede seguir la ruta directa."""
    intent = classify_agent_intent(prompt)
    if not intent.requires_mutation:
        # Preguntas simples no requieren descomposición en plan
        return False

    cleaned = prompt.strip()
    create_count = len(_CREATE_PATTERNS.findall(cleaned)) + len(_REQUEST_SUBJUNCTIVE_CREATE.findall(cleaned))
    update_count = len(_UPDATE_PATTERNS.findall(cleaned))
    delete_count = len(_DELETE_PATTERNS.findall(cleaned))
    relation_count = (
        len(_RELATION_PATTERNS.findall(cleaned))
        + len(_REQUEST_SUBJUNCTIVE_RELATE.findall(cleaned))
        + int(bool(_RELATION_CONFIGURATION_PATTERNS.search(cleaned)))
        + len(_ACTION_ON_RELATION_OR_ANAPHORA.findall(cleaned))
    )
    mutation_count = create_count + update_count + delete_count + relation_count

    has_query = bool(_QUERY_PATTERNS.search(cleaned)) or "?" in cleaned or "¿" in cleaned
    has_sequence = bool(_SEQUENCE_MARKERS.search(cleaned))

    has_classes_and_relations = bool(
        re.search(r"\bclases\b", cleaned, re.IGNORECASE)
        and re.search(
            r"\b(?:relaciones|asociaci[oó]n|composici[oó]n|agregaci[oó]n|generalizaci[oó]n|herencia)\b",
            cleaned,
            re.IGNORECASE,
        )
        and (create_count > 0 or relation_count > 0)
    )

    return (
        mutation_count > 1
        or (mutation_count > 0 and has_query)
        or has_sequence
        or bool(_EXPLICIT_BATCH.search(cleaned))
        or has_classes_and_relations
    )
