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
    r"cambia(?:r)?\s+(?:el\s+)?nombre|sincroni[zs]a(?:r|lo|la|los|las)?|sin\s*croni[zs]a(?:r|lo|la|los|las)?|"
    r"despliega(?:r)?|migra(?:r)?|sync|edit|update|rename|modify|adjust)\b",
    re.IGNORECASE,
)
_DELETE_PATTERNS = re.compile(
    r"\b(elimina(?:r)?|borra(?:r)?|quita(?:r)?|remueve(?:r)?|suprime(?:r)?|"
    r"delete|remove)\b",
    re.IGNORECASE,
)
_RELATION_PATTERNS = re.compile(
    r"\b(relaci[oó]na(?:r|la|lo|las|los)?|con[eé]cta(?:r|la|lo|las|los)?|vinc[uú]la(?:r|la|lo|las|los)?|"
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
    r"\b(?:quiero|necesito|pido|solicito)\s+que\s+(?:me\s+)?(?:crees|haga(?:s)?)\b|"
    r"\b(?:coloques?|colocar|col[oó]calos?|col[oó]calas?|agr[eé]galos?|agr[eé]galas?|"
    r"a[ñn][aá]delos?|a[ñn][aá]delas?|p[oó]nlos?|p[oó]nlas?|cr[eé]alos?|cr[eé]alas?)\b",
    re.IGNORECASE,
)
_REQUEST_SUBJUNCTIVE_RELATE = re.compile(
    r"\b(?:quiero|necesito|pido|solicito)\s+que\s+(?:me\s+)?relaciones\b",
    re.IGNORECASE,
)
_QUERY_PATTERNS = re.compile(
    r"\b(qué|dime|consulta(?:r)?|busca(?:r)?|explica(?:r)?|describe|describir|"
    r"revisa(?:r)?|cuál|cual|cuáles|cuales|cuántas|cuantas|cuántos|cuantos|"
    r"lista(?:r)?|muestra|muéstrame|muestrame|sugiere|recomienda|aconseja|"
    r"how|what|analyze|inspect|tell\s+me)\b",
    re.IGNORECASE,
)
_NEGATION_PATTERNS = re.compile(
    r"\b(no\s+(?:crees|creas|crear|hagas|hacer|borres|borrar|elimines|eliminar|"
    r"agregues|agregar|añadas|añadir|modifiques|modificar|actualices|actualizar|"
    r"quites|quitar|remuevas|remover|cambies|cambiar|relaciones|relacionar|toques|toque|nada))\b",
    re.IGNORECASE,
)
_HYPOTHETICAL_OR_DOUBT_PATTERNS = re.compile(
    r"\b(debería|deberia|podría|podria|sería\s+bueno|seria\s+bueno|se\s+puede|conviene|"
    r"qué\s+me\s+recomiendas|que\s+me\s+recomiendas|qué\s+sugieres|que\s+sugieres)\b",
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


def is_neon_sync_prompt(prompt: str) -> bool:
    """Detecta si la orden solicita sincronizar, migrar o desplegar la base de datos en Neon."""
    clean = prompt.strip().casefold()
    if not clean:
        return False
    has_sync_verb = bool(re.search(
        r"\b(?:sincroni[zs]a(?:r|lo|la|los|las)?|sin\s*croni[zs]a(?:r|lo|la|los|las)?|despliega(?:r)?|migra(?:r)?|actualiza(?:r)?|sync)\b",
        clean,
    ))
    has_neon_ref = any(term in clean for term in ("neon", "postgres", "postgresql", "base de datos", "bd", "proyecto"))
    if has_sync_verb and has_neon_ref:
        return True
    if "neon" in clean and any(w in clean for w in ("sincron", "desplieg", "migra", "actualiz")):
        return True
    return False


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
    has_compound_order = bool(
        _SEQUENCE_MARKERS.search(cleaned)
        or re.match(
            r"^(?:por\s+favor\s+)?\b(?:crea|haz|agrega|añade|genera|modifica|edita|actualiza|elimina|borra|quita|relaciona|conecta|vincula)\b",
            cleaned,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:y\s+)?(?:col[oó]ca(?:l[ao]s?)?|agr[eé]ga(?:l[ao]s?)?|p[oó]n(?:l[ao]s?)?|cr[eé]a(?:l[ao]s?)?|aplicar?|hazl[ao]|a[ñn][aá]de(?:l[ao]s?)?)\b",
            cleaned,
            re.IGNORECASE,
        )
    )
    if (is_hypothetical or is_question) and not has_compound_order:
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

    if is_neon_sync_prompt(cleaned) and not _NEGATION_PATTERNS.search(cleaned):
        return AgentIntent(
            action="update",
            target=cleaned,
            scope="neon",
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
        or is_neon_sync_prompt(prompt)
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

    # Operaciones atómicas de sincronización con Neon (sin mutaciones previas en el diagrama) se ejecutan directamente
    is_atomic_neon_op = is_neon_sync_prompt(cleaned) and not any(
        kw in cleaned.lower()
        for kw in (
            "crea", "crear", "agrega", "agregar", "elimina", "eliminar", "borra", "borrar",
            "modifica", "modificar", "y luego", "después", "despues", "además", "ademas"
        )
    )
    if is_atomic_neon_op:
        return False

    # Operaciones atómicas de Notion (crear, actualizar o eliminar una tarea) no requieren descomposición en DAG
    is_atomic_notion_op = "notion" in cleaned.lower() and any(
        kw in cleaned.lower()
        for kw in (
            "create_notion_task",
            "update_notion_task",
            "delete_notion_task",
            "crear una nueva tarea en notion",
            "crear una tarea en notion",
            "agrega esa sugerencia a una tarea",
            "crear tarea en notion",
        )
    ) and not any(
        kw in cleaned.lower()
        for kw in (
            "ejecutar tarea",
            "ejecuta la tarea",
            "realiza la tarea",
            "haz la tarea",
            "marcar la tarea como done",
        )
    )
    if is_atomic_notion_op:
        return False

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

    has_query = bool(_QUERY_PATTERNS.search(cleaned)) or "?" in cleaned or "¿" in cleaned or bool(_HYPOTHETICAL_OR_DOUBT_PATTERNS.search(cleaned))
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
