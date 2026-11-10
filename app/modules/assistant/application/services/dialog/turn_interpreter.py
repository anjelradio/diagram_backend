"""Intérprete de turnos de diálogo: clasifica la intención estructurada y extrae slots."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    ModelRole,
)
from app.modules.assistant.application.services.dialog.context_assembler import (
    AssembledTurnContext,
)
from app.modules.assistant.application.services.planning.agent_intent import classify_agent_intent
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState
from app.modules.assistant.domain.dialog.slot_schema import (
    normalize_cardinality,
    normalize_relation_type,
)
from app.modules.assistant.application.services.dialog.turn_signals import (
    _ABANDON_PATTERN,
    extract_turn_signals,
    normalize_text,
    TurnSignals,
)

logger = logging.getLogger(__name__)

_DECLINE_TERMS = (
    "cancela",
    "cancelar",
    "ya no hagas nada",
    "no hagas nada",
    "dejalo asi",
    "déjalo así",
    "olvidalo",
    "olvídalo",
    "descartar",
    "descarta",
    "abortar",
    "no quiero",
)

_CONFIRM_TERMS = (
    "ok, hazlo",
    "ok hazlo",
    "hazlo",
    "procede",
    "dale",
    "de acuerdo",
    "confirmo",
    "adelante",
    "si, hazlo",
    "sí, hazlo",
)

_CONFIRM_PATTERN = re.compile(
    r"^(?:si\b|ok\b|okay\b|yes\b|dale\b|hazlo\b|procede\b|adelante\b|vale\b|claro\b|perfecto\b|de acuerdo\b|confirmo\b|me parece bien\b)",
    re.IGNORECASE,
)

_ADDITION = re.compile(r"(?:[,.;]\s*|\s+)(?:y\s+)?(?:adem[aá]s|luego|despu[eé]s)\s*[:,]?\s+", re.IGNORECASE)
_OPTION_REFERENCE = re.compile(
    r"^(?:(?:implementa|aplica|elige|prefiero)\s+)?(?:la\s+)?opci[oó]n\s+(\w+)[.!]?$",
    re.IGNORECASE,
)
_RELATION_COMMAND = re.compile(
    r"^(?:mejor\s+)?(?:relaciona(?:r)?|conecta(?:r)?|(?:haz|crea)\s+(?:una\s+)?relaci[oó]n"
    r"(?:\s+de\s+(?:tipo\s+)?(?P<type>\w+)(?=\s+entre))?)"
    r"\s+(?:entre\s+)?(?:la\s+clase\s+)?`?(?P<source>[^\W\d]\w*)`?\s+(?:y|con)"
    r"\s+(?:la\s+clase\s+)?`?(?P<target>[^\W\d]\w*)`?",
    re.IGNORECASE,
)
_NAMED_CLASS_COMMAND = re.compile(
    r"^(?:mejor\s+)?(?:crea(?:r)?|haz|agrega(?:r)?|a[ñn]ade(?:r)?)\s+(?:(?:una|la)\s+)?clase\b"
    r"(?:\s+llamada\b)?(?:\s+`?([^\W\d]\w*))?",
    re.IGNORECASE,
)
_RELATION_SEPARATOR = re.compile(
    r"(?:[.;,]\s*|\s+y\s+)(?:tambi[eé]n\s+|adem[aá]s\s+)?(?=(?:crea|haz|relaciona|conecta)\b)",
    re.IGNORECASE,
)
_PAIR_ANSWER = re.compile(
    r"(?:^|[,;.]\s*(?:y\s+)?|\s+y\s+)(?:para|entre)\s+([^\W\d]\w*)\s+y\s+([^\W\d]\w*)\s+",
    re.IGNORECASE,
)
_RECOMMEND_PATTERN = re.compile(
    r"\b(?:recomiend\w*|recomend(?:ar|aci[oó]n)\w*|sugier\w*|suger(?:ir|encia\w*)|aconsej\w*|cu[aá]l\s+(?:es\s+)?mejor|qu[eé]\s+(?:es\s+)?mejor)\b",
    re.IGNORECASE,
)

_EXPLICIT_RETRY_PATTERN = re.compile(
    r"\b(?:reintenta\w*|reintentar|reanuda\w*|reanudar|contin[uú]a(?:\s+con)?|sigue(?:\s+con)?)\b",
    re.IGNORECASE,
)

_TOPIC_SWITCH = re.compile(
    r"^(?:olv[ií]da(?:te)?(?:\s+(?:de\s+)?(?:eso|ello|est[oe]|aquello|lo\s+anterior|anterior))?|"
    r"cancela(?:\s+(?:de\s+)?(?:eso|ello|est[oe]|la\s+solicitud|lo\s+anterior))?|"
    r"dej[eé]moslo\s+(?:as[ií]|ah[ií])|d[eé]jalo\s+(?:as[ií]|ah[ií])|"
    r"ignora\s+(?:lo\s+)?anterior|dejemos\s+(?:lo\s+)?anterior|"
    r"cambiemos\s+de\s+tema)\s*[,;:.]?\s*"
    r"(?:(?:y\s+|pero\s+)?(?:mejor\s+|ahora\s+)?|(?:en\s+vez\s+de\s+eso\s+|en\s+lugar\s+de\s+eso\s+))?"
    r"(?:quiero\s+que\s+)?(?P<request>.+)$",
    re.IGNORECASE,
)

_RESERVED_ATTR_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "clase", "clases", "tabla", "tablas", "relacion", "relaciones", "relación",
    "atributo", "atributos", "campo", "campos", "diagrama", "diagramas",
    "metodo", "metodos", "método", "métodos", "de", "en", "para", "a", "con",
    "y", "e", "o", "u", "que", "pero", "por", "sobre", "sin",
})


def is_explicit_diagram_question(prompt: str) -> bool:
    intent = classify_agent_intent(prompt)
    return (
        intent.is_question
        and not intent.requires_mutation
        and bool(re.search(r"\bclase\s+(?!esa\b|esta\b)\w+|\b(?:para|de)\s+[A-Z]\w*\b", prompt))
        and not bool(re.search(r"\b(?:m[aá]s|otra|esa|ese|esas|esos)\b", prompt, re.IGNORECASE))
    )


def starts_independent_class_request(prompt: str) -> bool:
    """Una orden con nombre propio puede empezar otro flujo sin consultar aclaraciones visuales."""
    match = _NAMED_CLASS_COMMAND.match(prompt.strip())
    return bool(
        match
        and match.group(1)
        and match.group(1).casefold() not in {"con", "y", "para", "de"}
        and not re.search(r"\b(?:imagen|adjunt[ao]|captura|foto)\b", prompt, re.IGNORECASE)
    )


def _is_explicit_retry(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if clean in {"reintenta", "reintentar", "continúa", "continua", "sigue", "reanuda", "reanudar"}:
        return True
    return bool(_EXPLICIT_RETRY_PATTERN.search(clean))


@dataclass(frozen=True, slots=True)
class InterpretedTurn:
    """Resultado estructurado de la interpretación del turno del usuario."""

    user_act: str  # "new_request" | "provide_slots" | "accept_proposal" | "confirm" | "decline" | "consult" | "correct" | "retry" | "abandon" | "select_option" | "ambiguous_target" | "read_only"
    slots: dict[str, Any] = field(default_factory=dict)
    proposed_action: str | None = None
    target_frame_id: str | None = None
    rationale: str | None = None
    raw_message: str = ""
    additional_request: str | None = None
    secondary_requests: tuple[str, ...] = ()
    new_relation_slots: tuple[dict[str, Any], ...] = ()
    frame_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    option_label: str | None = None
    thread_effect: str = "keep"  # "keep" | "abandon" | "topic_change"
    context_dependency: str = "none"  # "none" | "open_thread" | "recent_exchange"
    confidence: float = 1.0


class TurnInterpreter:
    """Clasifica el acto conversacional del usuario y extrae slots determinista o vía LLM."""

    def __init__(self, ai_provider: AiProvider | None = None) -> None:
        self.ai_provider = ai_provider

    def relation_slots_from_request(self, request: str) -> dict[str, Any]:
        """Extrae los datos conocidos de una orden de relación antes de planificar."""
        match = _RELATION_COMMAND.match(request.strip())
        return self._relation_slots(request.strip(), match) if match else {}

    async def interpret(
        self,
        *,
        user_message: str,
        dialog_state: DialogState | None = None,
        context: AssembledTurnContext | None = None,
    ) -> InterpretedTurn:
        clean = user_message.strip()
        signals = extract_turn_signals(clean)

        topic_switch = _TOPIC_SWITCH.fullmatch(clean)
        if topic_switch:
            request = topic_switch.group("request").strip()
            is_abandon_remainder = (
                bool(_ABANDON_PATTERN.match(request))
                or any(request.casefold().startswith(dt) for dt in ("ya no", "no hagas", "dejalo", "dejemos", "cancela", "olvida"))
            )
            if not is_abandon_remainder:
                parsed = self._try_deterministic_parse(
                    clean=request,
                    norm_text=request.casefold(),
                    dialog_state=None,
                )
                return InterpretedTurn(
                    user_act="new_request",
                    proposed_action=parsed.proposed_action if parsed else "UNKNOWN",
                    slots=parsed.slots if parsed else {},
                    new_relation_slots=parsed.new_relation_slots if parsed else (),
                    raw_message=request,
                    rationale="Cambio de objetivo explícito.",
                    thread_effect="topic_change",
                )

        # 0. Abandono explícito ("olvídate de eso", "cancela eso")
        if signals.is_explicit_abandon:
            return InterpretedTurn(
                user_act="abandon",
                thread_effect="abandon",
                raw_message=user_message,
                rationale="Abandono explícito de la solicitud o hilo.",
            )

        primary = signals.primary_clause
        secondary_requests = signals.secondary_clauses
        additional_request = secondary_requests[0] if secondary_requests else None
        norm_text = signals.normalized_text

        # 1. Deterministic Fast-Paths
        # A. Decline
        is_correction = bool(re.search(r"^(?:no,\s*mejor|no\s+espera|en\s+vez\s+de)", norm_text))
        if not is_correction:
            parts = [part.strip(" .!¡") for part in norm_text.split(",")]
            if all(part == "no" or part in _DECLINE_TERMS for part in parts) or signals.is_decline:
                return InterpretedTurn(
                    user_act="decline",
                    raw_message=user_message,
                    rationale="El usuario indicó cancelación explícita.",
                )

        # B. Affirmation / Option Reference / Accept Proposal / Confirm
        opt_label = signals.option_label or (
            _OPTION_REFERENCE.fullmatch(primary).group(1).casefold()
            if _OPTION_REFERENCE.fullmatch(primary)
            else None
        )
        if opt_label and (dialog_state and dialog_state.proposals or _OPTION_REFERENCE.search(clean)):
            return InterpretedTurn(
                user_act="select_option",
                raw_message=user_message,
                option_label=opt_label,
                additional_request=additional_request,
                secondary_requests=secondary_requests,
                thread_effect="keep",
            )

        is_accept_phrase = bool(
            re.search(
                r"^(?:quiero\s+que\s+)?(?:pon(?:gas)?|implementa(?:r|s)?|aplica(?:r|s)?|crea(?:r|s)?|agrega(?:r|s)?|a[ñn]ade(?:r|s)?|haz(?:lo)?)\s+"
                r"(?:(?:todos?\s+)?(?:es[ao]s?|est[ao]s?)\s+(?:relacion(?:es)?|generalizacion(?:es)?|herencia(?:s)?|asociacion(?:es)?|composicion(?:es)?|agregacion(?:es)?|dependencia(?:s)?|realizacion(?:es)?|atributos?|cambios?)"
                r"(?:\s+(?:a|en)\s+(?:es[ao]s?|est[ao]s?|las?)\s+clases?)?|"
                r"(?:la|las|los)\s+(?:propuestas?|sugerencias?|recomendaciones?|cambios?))\s*[.!]?$",
                norm_text,
            )
        )
        affirmative = norm_text.strip(" .!¡")
        prefix = _CONFIRM_PATTERN.match(affirmative)
        remainder = affirmative[prefix.end():].strip(" ,") if prefix else ""
        is_confirmation = (
            signals.is_affirmative
            or is_accept_phrase
            or bool(
                prefix and (
                    not remainder
                    or remainder in _CONFIRM_TERMS
                    or remainder in {"quiero que lo hagas", "crea esa relacion", "continua", "continúa", "sigue"}
                )
            )
        )
        if is_confirmation:
            if dialog_state and dialog_state.proposals:
                return InterpretedTurn(
                    user_act="accept_proposal",
                    raw_message=user_message,
                    additional_request=additional_request,
                    secondary_requests=secondary_requests,
                    rationale="El usuario aceptó la propuesta sugerida.",
                )
            if dialog_state and dialog_state.active_frame and dialog_state.active_frame.is_ready:
                return InterpretedTurn(
                    user_act="confirm",
                    raw_message=user_message,
                    additional_request=additional_request,
                    secondary_requests=secondary_requests,
                    rationale="El usuario confirmó la ejecución de la solicitud completa.",
                )
            if dialog_state and dialog_state.active_frame and not dialog_state.active_frame.is_ready:
                if dialog_state.active_frame.action == "CREATE_RELATION":
                    default_adoption = re.search(
                        r"\b(?:por\s+defecto|la\s+t[ií]pica|el\s+t[ií]pico|la\s+est[aá]ndar|el\s+est[aá]ndar|la\s+normal|lo\s+recomendado|la\s+sugerida|lo\s+sugerido)\b",
                        clean,
                        re.IGNORECASE,
                    )
                    if default_adoption:
                        slots = {
                            "relation.source_cardinality": "1",
                            "relation.target_cardinality": "0..*",
                        }
                        if not dialog_state.active_frame.slots.get("relation.type"):
                            slots["relation.type"] = "ASSOCIATION"
                        return InterpretedTurn(
                            user_act="provide_slots",
                            slots=slots,
                            raw_message=user_message,
                            additional_request=additional_request,
                            secondary_requests=secondary_requests,
                            rationale="El usuario adoptó la cardinalidad por convención.",
                        )
            if signals.is_retry:
                return InterpretedTurn(
                    user_act="retry",
                    raw_message=user_message,
                    additional_request=additional_request,
                    secondary_requests=secondary_requests,
                    rationale="El usuario solicitó reanudar o reintentar.",
                )
            return InterpretedTurn(
                user_act="confirm",
                raw_message=user_message,
                additional_request=additional_request,
                secondary_requests=secondary_requests,
                rationale="Confirmación sin propuesta ni solicitud previa identificable.",
            )

        # C. Isolated Key Request Guidance (FK / PK)
        if signals.is_fk_request:
            slots: dict[str, Any] = {}
            if signals.target_class_hint:
                slots["relation.source_class"] = signals.target_class_hint
            if signals.related_class_hint:
                slots["relation.target_class"] = signals.related_class_hint
            return InterpretedTurn(
                user_act="request_foreign_key_guidance",
                proposed_action="CREATE_RELATION",
                slots=slots,
                raw_message=user_message,
                additional_request=additional_request,
                secondary_requests=secondary_requests,
                rationale="El usuario solicitó crear una llave foránea de forma manual o aislada.",
            )

        if signals.is_pk_request:
            pk_slots: dict[str, Any] = {}
            if signals.target_class_hint:
                pk_slots["class.name"] = signals.target_class_hint
            return InterpretedTurn(
                user_act="request_primary_key_guidance",
                proposed_action="CREATE_CLASS",
                slots=pk_slots,
                raw_message=user_message,
                additional_request=additional_request,
                secondary_requests=secondary_requests,
                rationale="El usuario solicitó crear una llave primaria de forma manual.",
            )

        # D. Consult / Recommend
        intent = classify_agent_intent(clean)
        if is_explicit_diagram_question(clean):
            return InterpretedTurn(user_act="read_only", raw_message=user_message)
        if not intent.requires_mutation and (_RECOMMEND_PATTERN.search(norm_text) or _RECOMMEND_PATTERN.search(clean)):
            return InterpretedTurn(
                user_act="consult",
                raw_message=user_message,
                rationale="El usuario solicitó una recomendación.",
            )

        # D. Explicit Retry
        if _is_explicit_retry(clean):
            if dialog_state and dialog_state.proposals:
                return InterpretedTurn(
                    user_act="accept_proposal",
                    raw_message=user_message,
                    rationale="Continuación de una propuesta pendiente.",
                )
            if dialog_state and dialog_state.active_frame and not dialog_state.active_frame.is_ready:
                return InterpretedTurn(
                    user_act="provide_slots",
                    raw_message=user_message,
                    rationale="La solicitud todavía necesita los datos pendientes.",
                )
            return InterpretedTurn(
                user_act="retry",
                raw_message=user_message,
                rationale="El usuario solicitó un reintento explícito.",
            )

        if prefix and remainder:
            explicit = self._try_deterministic_parse(
                clean=primary[prefix.end():].lstrip(" ,"),
                norm_text=remainder,
                dialog_state=None,
            )
            if explicit and explicit.user_act == "new_request":
                return explicit

        clauses = _RELATION_SEPARATOR.split(clean)
        if len(clauses) > 1 and all(_RELATION_COMMAND.match(clause) for clause in clauses):
            relations = tuple(
                self._relation_slots(clause, match)
                for clause in clauses
                if (match := _RELATION_COMMAND.match(clause))
            )
            return InterpretedTurn(
                user_act="new_request",
                proposed_action="CREATE_RELATION",
                new_relation_slots=relations,
                raw_message=user_message,
            )
        if dialog_state and len(dialog_state.frames) > 1 and not _RELATION_COMMAND.match(primary):
            updates = self._match_grouped_answers(primary, dialog_state)
            if updates:
                return InterpretedTurn(
                    user_act="provide_slots",
                    frame_updates=updates,
                    additional_request=additional_request,
                    raw_message=user_message,
                )

        # E. Deterministic Slot Parsing
        deterministic_res = self._try_deterministic_parse(
            clean=primary if _RELATION_COMMAND.match(primary) or (dialog_state and dialog_state.active_frame) else clean,
            norm_text=norm_text,
            dialog_state=dialog_state,
        )
        if deterministic_res is not None:
            if (
                dialog_state and len(dialog_state.frames) > 1
                and deterministic_res.user_act in {"provide_slots", "correct"}
            ):
                return InterpretedTurn(user_act="ambiguous_target", raw_message=user_message)
            if additional_request and (
                deterministic_res.user_act in {"provide_slots", "correct"}
                or deterministic_res.proposed_action == "CREATE_RELATION"
            ):
                return InterpretedTurn(
                    user_act=deterministic_res.user_act,
                    slots=deterministic_res.slots,
                    proposed_action=deterministic_res.proposed_action,
                    raw_message=user_message,
                    additional_request=additional_request,
                )
            return deterministic_res

        # Una referencia libre a una propuesta también necesita interpretación,
        # aunque la propuesta no tenga un frame de mutación activo.
        if self.ai_provider is not None and dialog_state and (
            len(dialog_state.frames) == 1 or dialog_state.proposals
        ):
            try:
                return await self._llm_interpret(
                    user_message=user_message,
                    dialog_state=dialog_state,
                    context=context,
                )
            except Exception as exc:
                logger.warning("Fallo en LLM TurnInterpreter (%s)", type(exc).__name__)

        # 3. Default fallback as new_request or provide_slots
        if dialog_state and dialog_state.active_frame and not classify_agent_intent(user_message).requires_mutation:
            return InterpretedTurn(
                user_act="provide_slots",
                slots={},
                raw_message=user_message,
                additional_request=additional_request,
                secondary_requests=secondary_requests,
                context_dependency="open_thread",
                rationale="Fallback determinista en marco activo.",
            )
        return InterpretedTurn(
            user_act="new_request",
            proposed_action="UNKNOWN",
            slots={},
            raw_message=user_message,
            additional_request=additional_request,
            secondary_requests=secondary_requests,
            rationale="Fallback a nueva solicitud.",
        )

    def _match_grouped_answers(self, text: str, state: DialogState) -> dict[str, dict[str, Any]]:
        updates: dict[str, dict[str, Any]] = {}
        matches = list(_PAIR_ANSWER.finditer(text))
        for index, match in enumerate(matches):
            pair = {name.casefold() for name in match.groups()}
            frames = [
                frame for frame in state.frames
                if frame.action == "CREATE_RELATION"
                and {
                    str(slot.value).casefold() for key, slot in frame.slots.items()
                    if key in {"relation.source_class", "relation.target_class"}
                } == pair
            ]
            if len(frames) != 1:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            answer = text[match.end():end].strip()
            frame = frames[0]
            parsed = self._try_deterministic_parse(
                clean=answer,
                norm_text=answer.casefold(),
                dialog_state=DialogState(frames=[frame]),
            )
            if parsed and parsed.user_act in {"provide_slots", "correct"}:
                updates.setdefault(frame.id, {}).update(parsed.slots)
        return updates

    def _relation_slots(self, text: str, match: re.Match[str]) -> dict[str, Any]:
        slots = {
            "relation.source_class": match["source"],
            "relation.target_class": match["target"],
        }
        if relation_type := normalize_relation_type(match["type"]):
            slots["relation.type"] = relation_type
        frame = DialogFrame(id="relation", action="CREATE_RELATION")
        for key, value in slots.items():
            frame.set_slot(key, value)
        tail = text[match.end():].strip()
        if tail:
            parsed = self._try_deterministic_parse(
                clean=tail, norm_text=tail.casefold(), dialog_state=DialogState(frames=[frame])
            )
            if parsed and parsed.user_act in {"provide_slots", "correct"}:
                slots.update(parsed.slots)
        return slots

    def _relation_slots_from_text(self, text: str, frame: DialogFrame) -> dict[str, Any]:
        parsed = self._try_deterministic_parse(
            clean=text,
            norm_text=text.casefold(),
            dialog_state=DialogState(frames=[frame]),
        )
        return parsed.slots if parsed and parsed.user_act in {"provide_slots", "correct"} else {}

    def _try_deterministic_parse(
        self,
        *,
        clean: str,
        norm_text: str,
        dialog_state: DialogState | None,
    ) -> InterpretedTurn | None:
        is_correction = bool(re.search(r"^(?:no,\s*mejor|no\s+espera|en\s+vez\s+de)", norm_text))
        active_frame = dialog_state.active_frame if dialog_state else None

        # 1. Self-sufficient New Class Request: "Crea una clase llamada Factura", "Agrega la clase Producto"
        cls_init_match = _NAMED_CLASS_COMMAND.match(clean)
        if cls_init_match:
            cls_name = cls_init_match.group(1)
            if cls_name and cls_name.casefold() in {"con", "y", "para", "de"}:
                cls_name = None
            slots = {"class.name": cls_name} if cls_name else {}
            if not cls_name:
                details_start = cls_init_match.start(1) if cls_init_match.group(1) else cls_init_match.end()
                details = clean[details_start:].strip()
                if details:
                    slots["class.details"] = f" {details.rstrip('.')}"
            return InterpretedTurn(
                user_act="new_request",
                proposed_action="CREATE_CLASS",
                slots=slots,
                raw_message=clean,
                rationale="Solicitud autosuficiente de creación de clase.",
            )

        # 2. Self-sufficient New Relation Request with both endpoints explicitly specified
        rel_init_match = _RELATION_COMMAND.match(clean)
        if rel_init_match:
            return InterpretedTurn(
                user_act="new_request",
                proposed_action="CREATE_RELATION",
                slots=self._relation_slots(clean, rel_init_match),
                raw_message=clean,
                rationale="Solicitud explícita de relación entre dos clases.",
            )

        # 3. Self-sufficient New Attribute Request with target class specified or explicit attribute/campo keyword
        has_attr_keyword = bool(re.search(r"\b(?:atributos?|campos?)\b", clean, re.IGNORECASE))
        class_match = re.search(r"\b(?:en|para|a)\s+(?:la\s+clase\s+)?([^\W\d]\w*)", clean, re.IGNORECASE)
        if has_attr_keyword or (class_match and not starts_independent_class_request(clean)):
            attr_init_match = re.search(
                r"\b(?:agrega(?:r)?|agrea(?:r)?|agrga(?:r)?|crea(?:r)?|anade|añade|pon(?:er)?|coloca(?:r)?)\s+(?:(?:un|el|la|los|las)\s+)?(?:(?:atributos?|campos?)\s+)?(?:llamados?\s+|nombrados?\s+)?([^\W\d]\w*)",
                clean,
                re.IGNORECASE,
            )
            if attr_init_match:
                attr_name = attr_init_match.group(1).strip()
                if attr_name.casefold() not in _RESERVED_ATTR_WORDS:
                    target_cls = class_match.group(1).strip() if class_match else None
                    if target_cls and target_cls.casefold() in _RESERVED_ATTR_WORDS:
                        target_cls = None
                    slots = {"attribute.name": attr_name}
                    if target_cls:
                        slots["attribute.target_class"] = target_cls
                    return InterpretedTurn(
                        user_act="new_request",
                        proposed_action="CREATE_ATTRIBUTE",
                        slots=slots,
                        raw_message=clean,
                        rationale="Solicitud de creación de atributo.",
                    )

        # 4. Explicit independent commands (e.g. Deletion, Inspection, Diagram display)
        other_cmd_match = re.search(
            r"^(?:mejor\s+)?(?:elimina(?:r)?|borra(?:r)?|destruye|quita(?:r)?|edita|modifica|renombra|actualiza|muestra(?:r)?|enseña(?:r)?|dibuja(?:r)?|lista(?:r)?|qu[eé]\s+clases)\b",
            norm_text,
            re.IGNORECASE,
        )
        if other_cmd_match:
            return InterpretedTurn(
                user_act="new_request",
                proposed_action="UNKNOWN",
                slots={},
                raw_message=clean,
                rationale="Comando independiente nuevo.",
            )

        # 5. Context-dependent patterns when active_frame is present:
        if active_frame:
            act = "correct" if is_correction else "provide_slots"
            extracted_slots: dict[str, Any] = {}
            if active_frame.action == "CREATE_ATTRIBUTE":
                target_cls = active_frame.slots.get("attribute.target_class")
                if target_cls and not active_frame.slots.get("attribute.name"):
                    m_attr = re.search(
                        r"^(?:(?:mejor\s+)?(?:agrega(?:r)?|agrea(?:r)?|agrga(?:r)?|crea(?:r)?|a[ñn]ade(?:r)?|anade(?:r)?|pon(?:er)?|coloca(?:r)?)\s+(?:(?:un|el|los|las)\s+)?(?:atributos?\s+|campos?\s+)?(?:llamados?\s+)?)?`?([^\W\d][\w\s,]+)`?[.!]?$",
                        clean,
                        re.IGNORECASE,
                    )
                    if m_attr:
                        candidate_name = m_attr.group(1).strip()
                        stop_words = {"no", "si", "sí", "cancelar", "cancela", "nada", "ninguno", "ninguna"}
                        if candidate_name.casefold() not in stop_words:
                            return InterpretedTurn(
                                user_act=act,
                                slots={"attribute.name": candidate_name},
                                raw_message=clean,
                                rationale="Nombre de atributo provisto en contexto de clase activa.",
                            )
                if not target_cls:
                    m_cls = re.search(
                        r"^(?:(?:a|en|para)\s+(?:la\s+clase\s+|el\s+nodo\s+)?|(?:(?:la|el)\s+)?clase\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?[.!]?$",
                        clean,
                        re.IGNORECASE,
                    )
                    if m_cls:
                        cand_cls = m_cls.group(1).strip()
                        if cand_cls.casefold() not in {"atributo", "atributos", "campo", "campos", "no", "si", "sí", "cancela"}:
                            return InterpretedTurn(
                                user_act=act,
                                slots={"attribute.target_class": cand_cls},
                                raw_message=clean,
                                rationale="Clase destino provista en contexto de atributo activo.",
                            )
            if active_frame.action == "CREATE_CLASS" and re.fullmatch(r"`?[^\W\d]\w*`?[.!]?", clean):
                return InterpretedTurn(user_act=act, slots={"class.name": clean.strip("`.!")}, raw_message=clean)
            if active_frame.action == "CONSULT_ATTRIBUTE" and re.fullmatch(r"`?[^\W\d]\w*`?[.!]?", clean):
                return InterpretedTurn(user_act=act, slots={"attribute.target_class": clean.strip("`.!")}, raw_message=clean)
            if active_frame.action == "CONSULT_RELATION":
                pair = re.fullmatch(
                    r"(?:entre\s+)?`?([^\W\d]\w*)`?\s+(?:y|con)\s+`?([^\W\d]\w*)`?[.!]?",
                    clean, re.IGNORECASE,
                )
                if pair:
                    return InterpretedTurn(
                        user_act=act,
                        slots={"relation.source_class": pair.group(1), "relation.target_class": pair.group(2)},
                        raw_message=clean,
                    )
                if re.fullmatch(r"`?[^\W\d]\w*`?[.!]?", clean):
                    missing = [slot.key for slot in active_frame.missing_slots]
                    if missing:
                        return InterpretedTurn(
                            user_act=act,
                            slots={missing[0]: clean.strip("`.!")},
                            raw_message=clean,
                        )

            # A. Relation Type (dry or partial: "herencia", "que sea una asociación")
            norm_type = normalize_relation_type(clean)
            if norm_type:
                extracted_slots["relation.type"] = norm_type

            # B. Generalization direction
            # "Usuario es la clase padre", "Usuario es padre", "Perfil es la hija", "Perfil hereda de Usuario"
            super_match = re.search(
                r"\b([^\W\d]\w*)\s+(?:es\s+(?:la\s+)?)?(?:clase\s+)?(?:padre|superclase)\b",
                clean,
                re.IGNORECASE,
            )
            sub_match = re.search(
                r"\b([^\W\d]\w*)\s+(?:es\s+(?:la\s+)?)?(?:clase\s+)?(?:hija|subclase)\b",
                clean,
                re.IGNORECASE,
            )
            inherits_match = re.search(
                r"\b([^\W\d]\w*)\s+hereda\s+de\s+([^\W\d]\w*)\b",
                clean,
                re.IGNORECASE,
            )
            if inherits_match:
                extracted_slots["relation.type"] = "GENERALIZATION"
                extracted_slots["relation.subclass"] = inherits_match.group(1)
                extracted_slots["relation.superclass"] = inherits_match.group(2)
            elif super_match:
                extracted_slots["relation.type"] = extracted_slots.get("relation.type", "GENERALIZATION")
                super_cls = super_match.group(1)
                extracted_slots["relation.superclass"] = super_cls
                # Deduce subclass from active frame if possible
                s_cls = active_frame.slots.get("relation.source_class")
                t_cls = active_frame.slots.get("relation.target_class")
                if s_cls and t_cls:
                    extracted_slots["relation.subclass"] = t_cls.value if s_cls.value.casefold() == super_cls.casefold() else s_cls.value
            elif sub_match:
                extracted_slots["relation.type"] = extracted_slots.get("relation.type", "GENERALIZATION")
                sub_cls = sub_match.group(1)
                extracted_slots["relation.subclass"] = sub_cls
                s_cls = active_frame.slots.get("relation.source_class")
                t_cls = active_frame.slots.get("relation.target_class")
                if s_cls and t_cls:
                    extracted_slots["relation.superclass"] = t_cls.value if s_cls.value.casefold() == sub_cls.casefold() else s_cls.value

            # C. Composition / Aggregation direction / roles
            # "Categoria contiene a Producto", "Factura tiene DetalleFactura"
            contains_match = re.search(
                r"\b([^\W\d]\w*)\s+contiene\s+(?:a\s+)?([^\W\d]\w*)\b",
                clean,
                re.IGNORECASE,
            )
            has_match = re.search(
                r"\b([^\W\d]\w*)\s+tiene\s+(?:a\s+)?([^\W\d]\w*)\b",
                clean,
                re.IGNORECASE,
            )
            if contains_match:
                extracted_slots["relation.whole"] = contains_match.group(1)
                extracted_slots["relation.part"] = contains_match.group(2)
            elif has_match:
                extracted_slots["relation.whole"] = has_match.group(1)
                extracted_slots["relation.part"] = has_match.group(2)

            implements_match = re.search(
                r"\b([^\W\d]\w*)\s+implementa\s+(?:a\s+)?([^\W\d]\w*)\b",
                clean, re.IGNORECASE,
            )
            depends_match = re.search(
                r"\b([^\W\d]\w*)\s+depende\s+de\s+([^\W\d]\w*)\b",
                clean, re.IGNORECASE,
            )
            if implements_match:
                extracted_slots.update({
                    "relation.type": "REALIZATION",
                    "relation.implementer": implements_match.group(1),
                    "relation.contract": implements_match.group(2),
                })
            elif depends_match:
                extracted_slots.update({
                    "relation.type": "DEPENDENCY",
                    "relation.dependent": depends_match.group(1),
                    "relation.dependency": depends_match.group(2),
                })

            # D. Endpoint cardinalities
            s_cls = active_frame.slots.get("relation.source_class")
            t_cls = active_frame.slots.get("relation.target_class")

            def _matches_endpoint_name(token: str, class_val: Any) -> bool:
                if not class_val or not isinstance(class_val, str):
                    return False
                t = "".join(c for c in unicodedata.normalize("NFD", token.casefold()) if unicodedata.category(c) != "Mn").rstrip("s")
                c = "".join(c for c in unicodedata.normalize("NFD", class_val.casefold()) if unicodedata.category(c) != "Mn").rstrip("s")
                return t == c

            # D.1 Pattern: "un producto tiene una categoría y una categoría tiene entre 0 a muchos productos"
            # In natural UML reading: "A tiene [entre] <card> B" indicates that entity B has multiplicity <card>
            has_rel_matches = re.findall(
                r"(?:un|una|el|la)?\s*([^\W\d]\w*)\s+tiene\s+(?:entre\s+)?(0\s+a\s+muchos|1\s+a\s+muchos|muchos|varios|un|una|uno|1|0\.\.1|0\.\.\*|1\.\.\*)\s+([^\W\d]\w*)",
                clean,
                re.IGNORECASE,
            )
            if has_rel_matches and s_cls and t_cls:
                for _subj, card_raw, target_item in has_rel_matches:
                    norm_c = normalize_cardinality(card_raw)
                    if _matches_endpoint_name(target_item, s_cls.value):
                        extracted_slots["relation.source_cardinality"] = norm_c
                    elif _matches_endpoint_name(target_item, t_cls.value):
                        extracted_slots["relation.target_cardinality"] = norm_c
                if extracted_slots.get("relation.source_cardinality") or extracted_slots.get("relation.target_cardinality"):
                    if not active_frame.slots.get("relation.type"):
                        extracted_slots.setdefault("relation.type", "ASSOCIATION")

            # D.2 Pattern: "<card> en <Clase>" or "<Clase> tiene/con/de <card>"
            if "relation.source_cardinality" not in extracted_slots and "relation.target_cardinality" not in extracted_slots:
                card_named_match = re.findall(
                    r"([0-9\.\*]+|muchos|varios|un|una|uno)\s+en\s+([^\W\d]\w*)",
                    clean,
                    re.IGNORECASE,
                )
                if not card_named_match:
                    card_named_match = [
                        (card_val, cls_name)
                        for cls_name, card_val in re.findall(
                            r"([^\W\d]\w*)\s+(?:tiene|con|de)\s+(?:entre\s+)?([0-9\.\*]+|muchos|varios|0\.\.1|0\.\.\*|1\.\.\*|1)\b",
                            clean,
                            re.IGNORECASE,
                        )
                    ]
                if card_named_match:
                    for card_val, cls_name in card_named_match:
                        norm_c = normalize_cardinality(card_val)
                        if s_cls and _matches_endpoint_name(cls_name, s_cls.value):
                            extracted_slots["relation.source_cardinality"] = norm_c
                        elif t_cls and _matches_endpoint_name(cls_name, t_cls.value):
                            extracted_slots["relation.target_cardinality"] = norm_c
                    if extracted_slots.get("relation.source_cardinality") or extracted_slots.get("relation.target_cardinality"):
                        if not active_frame.slots.get("relation.type"):
                            extracted_slots.setdefault("relation.type", "ASSOCIATION")
                else:
                    ratio_match = re.search(r"(?<!\w)(1|0\.\.1|muchos|0\.\.\*|1\.\.\*)\s+a\s+(0\.\.1|muchos|0\.\.\*|1\.\.\*|1)(?![\w*]|\.\.)", clean, re.IGNORECASE)
                    default_adoption_match = re.search(
                        r"\b(?:por\s+defecto|la\s+t[ií]pica|el\s+t[ií]pico|la\s+est[aá]ndar|el\s+est[aá]ndar|la\s+normal|lo\s+recomendado|la\s+sugerida|lo\s+sugerido)\b",
                        clean,
                        re.IGNORECASE,
                    )
                    if ratio_match:
                        extracted_slots["relation.source_cardinality"] = normalize_cardinality(ratio_match.group(1))
                        extracted_slots["relation.target_cardinality"] = normalize_cardinality(ratio_match.group(2))
                        if not active_frame.slots.get("relation.type"):
                            extracted_slots.setdefault("relation.type", "ASSOCIATION")
                    elif default_adoption_match:
                        extracted_slots["relation.source_cardinality"] = "0..*"
                        extracted_slots["relation.target_cardinality"] = "1"
                        if not active_frame.slots.get("relation.type"):
                            extracted_slots.setdefault("relation.type", "ASSOCIATION")

            # E. Attribute target class
            # "En la clase Usuario", "A la clase Producto", "En Usuario"
            attr_cls_match = re.search(
                r"\b(?:en|para|a|de)\s+(?:la\s+clase\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
                clean,
                re.IGNORECASE,
            )
            if attr_cls_match and active_frame.action in {"CREATE_ATTRIBUTE", "CONSULT_ATTRIBUTE"}:
                extracted_slots["attribute.target_class"] = attr_cls_match.group(1)

            # F. Relation name / label
            name_match = re.search(
                r"\b(?:con\s+(?:el\s+)?nombre|con\s+(?:la\s+)?etiqueta|con\s+(?:el\s+)?label|llamada|nombrada)\s+[`\"']?([^\W\d]\w*)[`\"']?",
                clean,
                re.IGNORECASE,
            )
            if name_match and active_frame.action in {"CREATE_RELATION", "CONSULT_RELATION"}:
                extracted_slots["relation.name"] = name_match.group(1).strip()

            if extracted_slots:
                return InterpretedTurn(
                    user_act=act,
                    slots=extracted_slots,
                    raw_message=clean,
                )

        return None

    async def _llm_interpret(
        self,
        *,
        user_message: str,
        dialog_state: DialogState | None,
        context: AssembledTurnContext | None,
    ) -> InterpretedTurn:
        assert self.ai_provider is not None
        system_prompt = (
            "Eres un intérprete conversacional de diálogos para un asistente de modelado UML.\n"
            "Tu tarea es analizar el mensaje del usuario en el contexto actual y retornar un JSON con:\n"
            "{\n"
            '  "user_act": "new_request" | "provide_slots" | "accept_proposal" | "decline" | "read_only" | "consult" | "correct",\n'
            '  "action": "CREATE_RELATION" | "CREATE_ATTRIBUTE" | "CREATE_CLASS" | "UNKNOWN" | null,\n'
            '  "slots": { [clave_slot]: valor },\n'
            '  "rationale": "Breve explicación en español"\n'
            "}\n"
            "Reglas:\n"
            "- Extrae solo datos expresados en el mensaje. No deduzcas una aprobación ni agregues acciones.\n"
            "- Si el usuario pide consejo: 'consult'.\n"
            "- Si el usuario corrige una decisión anterior: 'correct'.\n"
            "- Si aporta datos requeridos: 'provide_slots'.\n"
            "- Si acepta la propuesta pendiente con otras palabras: 'accept_proposal'.\n"
            "- Si pide una consulta independiente: 'read_only'. Si cambia de objetivo: 'new_request'.\n"
            "- No confirmes una propuesta si el mensaje solo pide información o contiene una negación.\n"
            "- Responde ÚNICAMENTE con el objeto JSON."
        )
        payload = {
            "user_message": user_message,
            "dialog_state": dialog_state.to_dict() if dialog_state else None,
            "recent_turns": context.recent_turns if context else [],
        }
        req = AiRequest(
            model_role=ModelRole.MAIN,
            messages=(
                AiMessage(role="system", content=system_prompt),
                AiMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ),
            response_format="json_object",
            purpose="dialog_turn_interpretation",
            enable_reasoning=False,
        )
        resp = await self.ai_provider.complete(req)
        raw_text = resp.text.strip()
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            raise ValueError("Resultado de análisis inválido.")
        act = data.get("user_act")
        slots = data.get("slots", {})
        if act not in ("new_request", "provide_slots", "accept_proposal", "decline", "read_only", "consult", "correct") or not isinstance(slots, dict):
            raise ValueError("Acto o campos de análisis inválidos.")
        if not all(isinstance(key, str) for key in slots.keys()):
            raise ValueError("Las claves de los campos del análisis deben ser texto.")
        action = data.get("action")
        if act == "accept_proposal" and not (dialog_state and dialog_state.proposals):
            raise ValueError("No hay una propuesta pendiente para aceptar.")
        if act == "provide_slots" and not (dialog_state and dialog_state.active_frame):
            raise ValueError("No hay campos pendientes que completar.")
        if act == "read_only" and classify_agent_intent(user_message).requires_mutation:
            raise ValueError("Una orden de mutación no puede enrutarse como consulta.")
        if act == "new_request" and not classify_agent_intent(user_message).requires_mutation:
            raise ValueError("La nueva solicitud requiere una orden explícita.")
        return InterpretedTurn(
            user_act=act,
            slots=slots,
            proposed_action=action if action in ("CREATE_RELATION", "CREATE_ATTRIBUTE", "CREATE_CLASS") else "UNKNOWN",
            rationale=data.get("rationale"),
            raw_message=user_message,
        )
