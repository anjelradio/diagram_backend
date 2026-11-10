"""Servicio para clasificar y resolver la continuidad conversacional con el agente."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    ModelRole,
)
from app.modules.assistant.application.services.planning.agent_intent import classify_agent_intent
from app.modules.assistant.application.services.planning.agent_prompts import (
    CONTINUATION_RESOLVER_PROMPT,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptCompositionContext,
)
from app.modules.assistant.domain.entities.agent_continuation import AgentContinuation

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_DECLINE_TERMS = {
    "no",
    "cancela",
    "cancelar",
    "olvídalo",
    "olvidalo",
    "déjalo así",
    "dejalo asi",
    "ya no quiero",
    "no hagas nada",
    "descartar",
    "descarta",
}


_CONFIRMATION = re.compile(
    r"^(?:s[ií]|contin[uú]a(?:r)?|sigue|hazlo|procede|dale|ok|yes|adelante)\b"
)
_REFERENCE = re.compile(
    r"\b(?:quiero\s+que\s+)?"
    r"(?:pon|pongas|agrega|agregues|anade|anadas|crea|crees|edita|modifica|"
    r"implementa|aplica|elimina|borra)\s+"
    r"(?:(?:los|las)\s+)?(?:(?:todos|todas)\s+)?"
    r"(?:eso|esto|esa|ese|esas|esos|estas|estos|lo anterior|lo acordado|lo sugerido|la opcion)\b"
)


_RECOMMENDATION = re.compile(
    r"\b(?:recomiend\w*|recomend\w*|sugier\w*|suger\w*|aconsej\w*)\b"
)


def may_reference_recent_exchange(prompt: str, *, has_image: bool = False) -> bool:
    """Identifica confirmaciones, referencias y respuestas cortas sin acción propia."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", prompt.casefold())
        if unicodedata.category(char) != "Mn"
    ).strip(" ¡!.,")
    if not normalized:
        return False
    if _CONFIRMATION.match(normalized) or _REFERENCE.search(normalized):
        return True
    if has_image:
        return False
    intent = classify_agent_intent(prompt)
    if _is_recommendation_query(prompt):
        return True
    return intent.action == "none" and not intent.is_negated and len(normalized.split()) <= 8


def _is_recommendation_query(prompt: str) -> bool:
    intent = classify_agent_intent(prompt)
    return intent.is_question and not intent.requires_mutation and bool(_RECOMMENDATION.search(prompt.casefold()))


class ResolutionDecision(StrEnum):
    """Decisiones de resolución posibles según la especificación."""

    FOLLOW_UP = "follow_up"
    RECENT_FOLLOW_UP = "recent_follow_up"
    NEW_REQUEST = "new_request"
    DECLINE = "decline"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ContinuationResolution:
    """Resultado validado de la resolución de continuidad."""

    decision: ResolutionDecision
    candidate_id: UUID | None = None
    effective_request: str | None = None
    resolved_facts: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[dict[str, Any]] = field(default_factory=list)
    ambiguity_message: str | None = None
    additional_request: str | None = None


class ContinuationResolver:
    """Resuelve si un mensaje continúa un pendiente, inicia otra solicitud o la rechaza."""

    def __init__(
        self,
        ai_provider: AiProvider | None = None,
        *,
        prompt_composer: PromptComposer | None = None,
        max_candidates: int = 3,
        max_evidence_turns: int = 6,
    ) -> None:
        self.ai_provider = ai_provider
        self.prompt_composer = prompt_composer
        self.max_candidates = max_candidates
        self.max_evidence_turns = max_evidence_turns

    async def resolve(
        self,
        *,
        user_prompt: str,
        candidates: list[AgentContinuation],
        recent_messages: list[dict[str, Any]] | None = None,
        image_url: str | None = None,
    ) -> ContinuationResolution:
        clean_prompt = user_prompt.strip()

        recent_evidence = (recent_messages or [])[: self.max_evidence_turns]
        is_recommendation_query = _is_recommendation_query(clean_prompt)
        if not candidates and not recent_evidence:
            return ContinuationResolution(
                decision=ResolutionDecision.NEW_REQUEST,
                candidate_id=None,
                effective_request=clean_prompt,
            )

        # Fast path 2: Rechazo explícito con un único candidato abierto
        if (
            len(candidates) == 1
            and clean_prompt.lower() in _DECLINE_TERMS
            and (
                not recent_evidence
                or recent_evidence[-1].get("message_id") == str(candidates[0].latest_message_id)
            )
        ):
            return ContinuationResolution(
                decision=ResolutionDecision.DECLINE,
                candidate_id=candidates[0].id,
                effective_request=None,
            )

        valid_candidates = candidates[: self.max_candidates]
        candidate_ids = {c.id for c in valid_candidates}

        # Si no hay proveedor AI disponible (fallback determinista)
        if self.ai_provider is None:
            if recent_evidence or is_recommendation_query:
                return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)
            return self._fallback_resolve(clean_prompt, valid_candidates)

        # Serialización de contexto para la inferencia
        candidates_data = [
            {
                "id": str(c.id),
                "effective_request": c.effective_request,
                "latest_message_id": str(c.latest_message_id),
                "missing_fields": c.missing_fields,
                "resolved_facts": c.resolved_facts,
            }
            for c in valid_candidates
        ]

        prompt_payload = {
            "current_user_message": clean_prompt,
            "has_image": bool(image_url),
            "pending_candidates": candidates_data,
            "recent_conversation_turns": recent_evidence,
        }

        if self.prompt_composer is not None:
            bundle = self.prompt_composer.compose(
                PromptCompositionContext(
                    phase="continuation",
                    has_continuation=True,
                )
            )
            system_content = bundle.system_text
        else:
            system_content = CONTINUATION_RESOLVER_PROMPT

        request = AiRequest(
            model_role=ModelRole.MAIN,
            messages=(
                AiMessage(role="system", content=system_content),
                AiMessage(role="user", content=json.dumps(prompt_payload, ensure_ascii=False)),
            ),
            response_format="json_object",
            purpose="continuation_resolution",
            enable_reasoning=False,
        )

        try:
            response = await self.ai_provider.complete(request)
            resolution = self._parse_and_validate(
                response.text, candidate_ids, valid_candidates, clean_prompt,
                has_recent_evidence=bool(recent_evidence),
            )
            if is_recommendation_query and (
                resolution.decision in {ResolutionDecision.FOLLOW_UP, ResolutionDecision.DECLINE}
                or (
                    resolution.decision == ResolutionDecision.RECENT_FOLLOW_UP
                    and classify_agent_intent(resolution.effective_request or "").requires_mutation
                )
            ):
                return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)
            return resolution
        except Exception as exc:
            logger.warning("Fallo al clasificar continuidad con AI: %s", type(exc).__name__)
            if recent_evidence or is_recommendation_query:
                return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)
            return self._fallback_resolve(clean_prompt, valid_candidates)

    def _fallback_resolve(
        self,
        prompt: str,
        candidates: list[AgentContinuation],
    ) -> ContinuationResolution:
        """Resolución heurística mínima cuando no se suministra proveedor AI o falla la llamada."""
        if not candidates:
            return ContinuationResolution(
                decision=ResolutionDecision.NEW_REQUEST,
                candidate_id=None,
                effective_request=prompt,
            )

        clean_p = prompt.strip().lower()
        if clean_p in _DECLINE_TERMS:
            return ContinuationResolution(
                decision=ResolutionDecision.DECLINE,
                candidate_id=candidates[0].id if len(candidates) == 1 else None,
                effective_request=None,
            )

        if len(candidates) == 1:
            cand = candidates[0]
            if "asociaci" in clean_p:
                return ContinuationResolution(
                    decision=ResolutionDecision.FOLLOW_UP,
                    candidate_id=cand.id,
                    effective_request=f"{cand.effective_request}; tipo asociación",
                    resolved_facts=[{"key": "relation.type", "value": "ASSOCIATION"}],
                    missing_fields=[
                        {
                            "key": "relation.endpoint_cardinalities",
                            "action": "CREATE_RELATION",
                            "critical": True,
                            "question": "¿Cuáles son las cardinalidades en cada extremo?",
                        }
                    ],
                )

            # Extraer solo cardinalidades explícitamente presentes; NUNCA inventar valores
            card_matches = re.findall(
                r"(?:^|(?<=\s)|(?<=\b))(1\.\.\*|0\.\.\*|0\.\.1|1\.\.1|1)(?=\s|$|[.,;])",
                clean_p,
            )
            if card_matches:
                normalized = ["1" if c == "1..1" else c for c in card_matches]
                if len(normalized) >= 2:
                    return ContinuationResolution(
                        decision=ResolutionDecision.FOLLOW_UP,
                        candidate_id=cand.id,
                        effective_request=f"{cand.effective_request}; cardinalidades {normalized[0]} y {normalized[1]}",
                        resolved_facts=[
                            {"key": "relation.source_cardinality", "value": normalized[0]},
                            {"key": "relation.target_cardinality", "value": normalized[1]},
                        ],
                        missing_fields=[],
                    )
                else:
                    return ContinuationResolution(
                        decision=ResolutionDecision.FOLLOW_UP,
                        candidate_id=cand.id,
                        effective_request=f"{cand.effective_request}; cardinalidad {normalized[0]}",
                        resolved_facts=[
                            {"key": "relation.source_cardinality", "value": normalized[0]},
                        ],
                        missing_fields=[
                            {
                                "key": "relation.target_cardinality",
                                "action": "CREATE_RELATION",
                                "critical": True,
                                "question": "¿Cuál es la cardinalidad en el otro extremo?",
                            }
                        ],
                    )

            if (
                clean_p in {"sí", "si", "continúa", "continua", "procede", "dale", "ok", "yes", "adelante"}
                or _CONFIRMATION.match(clean_p)
            ):
                if cand.missing_fields:
                    return ContinuationResolution(
                        decision=ResolutionDecision.FOLLOW_UP,
                        candidate_id=cand.id,
                        effective_request=cand.effective_request,
                        resolved_facts=list(cand.resolved_facts),
                        missing_fields=list(cand.missing_fields),
                        ambiguity_message=f"Para continuar, aún falta: {cand.missing_fields[0].get('question', 'completar los datos requeridos')}",
                    )
                return ContinuationResolution(
                    decision=ResolutionDecision.FOLLOW_UP,
                    candidate_id=cand.id,
                    effective_request=cand.effective_request,
                    resolved_facts=list(cand.resolved_facts),
                    missing_fields=[],
                )

            # Si el candidato tenía campos faltantes y el usuario aporta un valor (ej. nombre "Casa")
            if cand.missing_fields:
                first_missing = cand.missing_fields[0]
                field_key = first_missing.get("key", "continuation.text")
                return ContinuationResolution(
                    decision=ResolutionDecision.FOLLOW_UP,
                    candidate_id=cand.id,
                    effective_request=f"{cand.effective_request}; {prompt}",
                    resolved_facts=[{"key": field_key, "value": prompt}],
                    missing_fields=list(cand.missing_fields[1:]),
                )

            return ContinuationResolution(
                decision=ResolutionDecision.FOLLOW_UP,
                candidate_id=cand.id,
                effective_request=f"{cand.effective_request}; {prompt}",
                resolved_facts=[{"key": "continuation.text", "value": prompt}],
                missing_fields=[],
            )

        return ContinuationResolution(
            decision=ResolutionDecision.AMBIGUOUS,
            candidate_id=None,
            effective_request=None,
            ambiguity_message="Hay varias solicitudes pendientes. ¿A cuál de ellas te refieres?",
        )

    def _parse_and_validate(
        self,
        raw_text: str,
        valid_candidate_ids: set[UUID],
        valid_candidates: list[AgentContinuation],
        user_prompt: str,
        *,
        has_recent_evidence: bool = False,
    ) -> ContinuationResolution:
        text = raw_text.strip()
        match = _JSON_BLOCK.search(text)
        if match:
            text = match.group(1)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)

        if not isinstance(data, dict):
            return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)

        raw_decision = str(data.get("decision", "")).strip().lower()
        if raw_decision not in (
            ResolutionDecision.FOLLOW_UP,
            ResolutionDecision.RECENT_FOLLOW_UP,
            ResolutionDecision.NEW_REQUEST,
            ResolutionDecision.DECLINE,
            ResolutionDecision.AMBIGUOUS,
        ):
            raw_decision = ResolutionDecision.NEW_REQUEST

        candidate_id: UUID | None = None
        raw_cid = data.get("candidate_id")
        if raw_cid:
            try:
                parsed_cid = UUID(str(raw_cid))
                if parsed_cid in valid_candidate_ids:
                    candidate_id = parsed_cid
                else:
                    # ID alucinado que no estaba entre los candidatos suministrados
                    logger.warning("El modelo devolvió candidate_id desconocido %s", raw_cid)
                    return ContinuationResolution(
                        decision=ResolutionDecision.NEW_REQUEST,
                        candidate_id=None,
                        effective_request=user_prompt,
                    )
            except Exception:
                candidate_id = None

        if raw_decision == ResolutionDecision.FOLLOW_UP and candidate_id is None:
            # No se puede hacer follow_up sin un candidato válido
            return ContinuationResolution(
                decision=ResolutionDecision.NEW_REQUEST,
                candidate_id=None,
                effective_request=user_prompt,
            )

        effective_request = data.get("effective_request")
        effective_request = (
            effective_request.strip()[:10000] if isinstance(effective_request, str) else None
        )
        if raw_decision == ResolutionDecision.RECENT_FOLLOW_UP and (
            not has_recent_evidence or candidate_id is not None or not effective_request
        ):
            return ContinuationResolution(decision=ResolutionDecision.AMBIGUOUS)

        resolved_facts = data.get("resolved_facts") or []
        if not isinstance(resolved_facts, list):
            resolved_facts = []
        resolved_facts = [
            fact for fact in resolved_facts
            if isinstance(fact, dict) and isinstance(fact.get("key"), str) and "value" in fact
        ]

        missing_fields = data.get("missing_fields") or []
        if not isinstance(missing_fields, list):
            missing_fields = []
        missing_fields = [
            {**field, "critical": field.get("critical", True)}
            for field in missing_fields
            if isinstance(field, dict)
            and isinstance(field.get("key"), str)
            and isinstance(field.get("question"), str)
            and isinstance(field.get("critical", True), bool)
        ]

        # "Sí" nunca actúa como valor de un campo ausente si el candidato tenía requisitos críticos
        norm_prompt = user_prompt.strip().lower()
        if (
            norm_prompt in {"sí", "si", "continúa", "continua", "procede", "dale", "ok", "yes", "adelante"}
            or _CONFIRMATION.match(norm_prompt)
        ):
            matched_candidate = next((c for c in valid_candidates if c.id == candidate_id), None)
            if matched_candidate and matched_candidate.missing_fields and not missing_fields:
                missing_fields = list(matched_candidate.missing_fields)

        ambiguity_message = data.get("ambiguity_message")
        if ambiguity_message:
            # Asegura que ningún UUID técnico se filtre al usuario
            ambiguity_message = _UUID_PATTERN.sub("la solicitud", str(ambiguity_message))

        additional_request = data.get("additional_request")
        if isinstance(additional_request, str):
            additional_request = additional_request.strip()
        if (
            raw_decision != ResolutionDecision.FOLLOW_UP
            or not isinstance(additional_request, str)
            or not additional_request
            or additional_request.casefold() not in user_prompt.casefold()
        ):
            additional_request = None

        return ContinuationResolution(
            decision=ResolutionDecision(raw_decision),
            candidate_id=candidate_id,
            effective_request=effective_request,
            resolved_facts=resolved_facts,
            missing_fields=missing_fields,
            ambiguity_message=ambiguity_message,
            additional_request=additional_request,
        )
