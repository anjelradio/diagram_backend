"""Gestor de diálogo conversacional (Amazon Lex / Alexa style): L0..L2 + CAS."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    AgentConversationReader,
    RecentExchange,
)
from app.modules.assistant.application.ports.providers.ai_provider import AiProvider
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    may_reference_recent_exchange,
)
from app.modules.assistant.application.services.dialog.context_assembler import (
    ContextAssembler,
)
from app.modules.assistant.application.services.dialog.dialog_policy import (
    DialogPolicy,
    PolicyDecision,
)
from app.modules.assistant.application.services.dialog.turn_interpreter import (
    InterpretedTurn,
    TurnInterpreter,
    is_explicit_diagram_question,
)
from app.modules.assistant.application.services.planning.agent_intent import classify_agent_intent
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState, Proposal
from app.modules.assistant.domain.dialog.slot_schema import normalize_relation_type
from app.modules.assistant.domain.dialog.semantic_validators import (
    validate_relation_semantics,
    validate_inheritance_cycle,
    validate_attribute_duplicate,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    MAX_ACTIVE_FACTS,
    MAX_ACTIVE_QUESTIONS,
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.repositories.agent_continuation_repository import (
    AgentContinuationRepository,
)

logger = logging.getLogger(__name__)


class GroundedRecommendationPort(Protocol):
    async def suggest_attributes(
        self, *, project_id: UUID, user_id: str, class_name: str,
        user_prompt: str, state: DialogState,
    ) -> PolicyDecision: ...

    async def suggest_relation(
        self, *, project_id: UUID, user_id: str, source_name: str,
        target_name: str, user_prompt: str, state: DialogState,
    ) -> PolicyDecision: ...


_RELATION_START = re.compile(
    r"\b(?:relaciona(?:r)?|conecta(?:r)?|(?:crea|haz)\s+(?:una\s+)?relaci[oó]n)\b",
    re.IGNORECASE,
)
_NEXT_COMMAND = re.compile(
    r"\s+(?:y\s+)?(?:luego|despu[eé]s|adem[aá]s)?\s*"
    r"(?=(?:crea|agrega|a[ñn]ade|edita|modifica|elimina|borra|relaciona|conecta)\b)",
    re.IGNORECASE,
)


def _has_independent_consult_target(prompt: str) -> bool:
    """Distingue una consulta con destino nombrado de una referencia al hilo abierto."""
    if re.search(r"\b(?:esa|ese|esos|esas|esta|este|estos|estas|otra|m[aá]s)\b", prompt, re.IGNORECASE):
        return False
    named = re.search(
        r"\b(?:para|de|en)\s+(?:(?:la|el)\s+)?(?:clase\s+)?([\w]+)\b",
        prompt,
        re.IGNORECASE,
    )
    if named and named.group(1).casefold() not in {"clase", "relacion", "relación", "atributo", "atributos"}:
        return True
    return bool(re.search(r"\bentre\s+[\w]+\s+y\s+[\w]+\b", prompt, re.IGNORECASE))


def _consult_matches_active_relation(prompt: str, frame: DialogFrame | None) -> bool:
    if frame is None or frame.action != "CREATE_RELATION":
        return False
    source = frame.slots.get("relation.source_class")
    target = frame.slots.get("relation.target_class")
    return bool(
        source and target
        and re.search(rf"\b{re.escape(str(source.value))}\b", prompt, re.IGNORECASE)
        and re.search(rf"\b{re.escape(str(target.value))}\b", prompt, re.IGNORECASE)
    )


@dataclass(frozen=True, slots=True)
class DialogTurnResult:
    """Resultado inmutable del análisis previo de la solicitud según el contrato."""

    status: str  # "ready_read_only" | "ready_to_execute" | "awaiting_input" | "declined" | "pass_through"
    effective_request: str | None = None
    assistant_message: str | None = None
    assistant_act: str | None = None
    continuation: AgentContinuation | None = None
    dialog_state: DialogState | None = None
    authorized_mode: str | None = None  # "read_only" | "execute" | None
    continuation_id: UUID | None = None
    continuation_version: int | None = None
    evidence_references: tuple[str, ...] = ()
    missing_fields: tuple[dict[str, Any], ...] = ()
    resolved_facts: tuple[dict[str, Any], ...] = ()
    intent: str | None = None
    rationale: str | None = None
    recent_turns: tuple[dict[str, Any], ...] | None = None

    def __post_init__(self) -> None:
        if self.continuation is not None:
            if self.continuation_id is None:
                object.__setattr__(self, "continuation_id", self.continuation.id)
            if self.continuation_version is None:
                object.__setattr__(self, "continuation_version", self.continuation.version)
        if self.authorized_mode is None:
            if self.status == "ready_to_execute":
                object.__setattr__(self, "authorized_mode", "execute")
            elif self.status == "ready_read_only":
                object.__setattr__(self, "authorized_mode", "read_only")


def extract_proposals_from_recent_exchanges(
    exchanges: Sequence[RecentExchange],
) -> list[Proposal]:
    """Extrae propuestas de intercambios recientes completados para recuperarlas sin hilo abierto."""
    proposals: list[Proposal] = []
    for ex in exchanges:
        if ex.is_superseded:
            continue
        has_proposal_question = bool(
            re.search(
                r"¿(?:quieres|deseas|te\s+gustar[ií]a)\s+que\s+(?:cree|haga|agregue|aplique|proceda)\b",
                ex.assistant_response or "",
                re.IGNORECASE,
            )
        )
        has_recommendation = bool(
            re.search(
                r"\b(?:la\s+relaci[oó]n\s+(?:m[aá]s\s+)?(?:adecuada|recomendada|correcta|apropiada)|"
                r"te\s+recomiendo|recomiendo|sugiero|conviene|la\s+mejor\s+opci[oó]n\s+es)\b",
                ex.assistant_response or "",
                re.IGNORECASE,
            )
        )
        if ex.assistant_act != "consult_with_proposal" and not has_proposal_question and not has_recommendation:
            continue
        if ex.proposals:
            for item in ex.proposals:
                try:
                    proposal = Proposal.from_dict(item)
                except (KeyError, TypeError, ValueError):
                    continue
                if proposal.action in {"CREATE_CLASS", "CREATE_ATTRIBUTE", "CREATE_RELATION"}:
                    proposals.append(proposal)
            continue
        resp = ex.assistant_response or ""
        # 1. Composición
        m_comp = re.search(
            r"\bcomposici[oó]n\b.*?(?:donde\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+(?:es el contenedor|es el todo|como el todo)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+(?:es la parte|como la parte)",
            resp,
            re.IGNORECASE,
        )
        if not m_comp:
            m_comp = re.search(
                r"\bcomposici[oó]n\b.*?\(([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+como el todo\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+como la parte\)",
                resp,
                re.IGNORECASE,
            )
        if m_comp:
            whole, part = m_comp.group(1).strip(), m_comp.group(2).strip()
            proposals.append(
                Proposal(
                    action="CREATE_RELATION",
                    slots={
                        "relation.type": "COMPOSITION",
                        "relation.source_class": whole,
                        "relation.target_class": part,
                        "relation.whole": whole,
                        "relation.part": part,
                    },
                    rationale=resp[:150],
                )
            )
            continue

        # 2. Asociación
        m_name = re.search(r"[«\"]([^»\"]+)[»\"]|etiqueta:\s*«?([^»)»]+)»?", resp)
        rel_label = (m_name.group(1) or m_name.group(2)).strip() if m_name else None

        m_assoc_paren = re.search(
            r"\basociaci[oó]n\b.*?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s*\(([^)]+)\)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s*\(([^)]+)\)",
            resp,
            re.IGNORECASE,
        )
        if m_assoc_paren:
            s_cls = m_assoc_paren.group(1).strip()
            s_card = m_assoc_paren.group(2).strip()
            t_cls = m_assoc_paren.group(3).strip()
            t_card = m_assoc_paren.group(4).strip()
            proposals.append(
                Proposal(
                    action="CREATE_RELATION",
                    slots={
                        "relation.type": "ASSOCIATION",
                        "relation.source_class": s_cls,
                        "relation.target_class": t_cls,
                        "relation.source_cardinality": s_card,
                        "relation.target_cardinality": t_card,
                        **({"relation.name": rel_label} if rel_label else {}),
                    },
                    rationale=resp[:150],
                )
            )
            continue

        m_assoc = re.search(
            r"\basociaci[oó]n(?:\s+de\s+(\S+)\s+a\s+(\S+))?\s+entre\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
            resp,
            re.IGNORECASE,
        )
        if not m_assoc:
            m_assoc = re.search(
                r"\basociaci[oó]n\b.*?(?:entre|de)\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                resp,
                re.IGNORECASE,
            )
        if m_assoc:
            if m_assoc.lastindex and m_assoc.lastindex >= 4:
                s_card = m_assoc.group(1)
                t_card = m_assoc.group(2)
                s_cls = m_assoc.group(3).strip()
                t_cls = m_assoc.group(4).strip()
            else:
                s_card, t_card = None, None
                s_cls = m_assoc.group(1).strip()
                t_cls = m_assoc.group(2).strip()
            proposals.append(
                Proposal(
                    action="CREATE_RELATION",
                    slots={
                        "relation.type": "ASSOCIATION",
                        "relation.source_class": s_cls,
                        "relation.target_class": t_cls,
                        **({"relation.source_cardinality": s_card} if s_card else {}),
                        **({"relation.target_cardinality": t_card} if t_card else {}),
                        **({"relation.name": rel_label} if rel_label else {}),
                    },
                    rationale=resp[:150],
                )
            )
            continue

        # 2b. Relación contextual o sugerida al final del mensaje (ej. "¿Quieres que cree esta relación?")
        m_rel_offer = re.search(
            r"(?:se\s+recomienda|recomiendo|sugiero|puedes|conviene)\s+(?:crear\s+)?(?:una\s+)?relaci[oó]n\s+(?:de\s+(\w+)\s+)?(?:entre\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)|entre\s+ambas\s+clases)",
            resp,
            re.IGNORECASE,
        )
        if not m_rel_offer and has_proposal_question and re.search(r"\brelaci[oó]n\b", resp, re.IGNORECASE):
            m_rel_offer = re.search(r"\brelaci[oó]n\b", resp, re.IGNORECASE)

        if m_rel_offer:
            rel_type_str = m_rel_offer.group(1) if hasattr(m_rel_offer, "lastindex") and m_rel_offer.lastindex and m_rel_offer.lastindex >= 1 else None
            norm_rel_type = normalize_relation_type(rel_type_str) or "ASSOCIATION"
            s_cls = m_rel_offer.group(2) if hasattr(m_rel_offer, "lastindex") and m_rel_offer.lastindex and m_rel_offer.lastindex >= 2 else None
            t_cls = m_rel_offer.group(3) if hasattr(m_rel_offer, "lastindex") and m_rel_offer.lastindex and m_rel_offer.lastindex >= 3 else None
            if not s_cls or not t_cls:
                m_direct = re.search(
                    r"\b([A-Z][a-z0-9_]+)\s+(?:pertenece|est[aá]|se\s+asocia|se\s+relaciona)\s+(?:a\s+(?:un[a]?\s+)?)?([A-Z][a-z0-9_]+)\b",
                    resp,
                )
                if m_direct:
                    s_cls, t_cls = m_direct.group(1), m_direct.group(2)
                else:
                    explicit_classes = re.findall(
                        r"\bclase\s+([A-Za-z0-9_]+)\b",
                        (ex.user_prompt or "") + " " + resp,
                        re.IGNORECASE,
                    )
                    cand_unique = []
                    for c in explicit_classes:
                        c_cap = c.capitalize()
                        if c_cap not in cand_unique:
                            cand_unique.append(c_cap)
                    if len(cand_unique) >= 2:
                        s_cls, t_cls = cand_unique[0], cand_unique[1]
            if s_cls and t_cls:
                s_card = "0..*"
                t_card = "1"
                rel_name = "pertenece"
                proposals.append(
                    Proposal(
                        action="CREATE_RELATION",
                        slots={
                            "relation.type": norm_rel_type,
                            "relation.source_class": s_cls,
                            "relation.target_class": t_cls,
                            "relation.source_cardinality": s_card,
                            "relation.target_cardinality": t_card,
                            "relation.name": rel_name,
                        },
                        rationale=resp[:150],
                    )
                )
                continue

        # 3. Herencia / Generalización
        m_super = re.search(
            r"\b([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+(?:es|como)\s+(?:la\s+)?(?:padre|superclase)\b|"
            r"\b(?:padre|superclase)\s+(?:es\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\b",
            resp,
            re.IGNORECASE,
        )
        m_sub = re.search(
            r"\b([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+(?:es|como)\s+(?:la\s+)?(?:hija|subclase)\b|"
            r"\b(?:hija|subclase)\s+(?:es\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\b",
            resp,
            re.IGNORECASE,
        )
        if (m_super and m_sub) and re.search(r"\b(?:herencia|generalizaci[oó]n)\b", resp, re.IGNORECASE):
            super_cls = (m_super.group(1) or m_super.group(2)).strip()
            sub_cls = (m_sub.group(1) or m_sub.group(2)).strip()
            proposals.append(
                Proposal(
                    action="CREATE_RELATION",
                    slots={
                        "relation.type": "GENERALIZATION",
                        "relation.source_class": super_cls,
                        "relation.target_class": sub_cls,
                        "relation.superclass": super_cls,
                        "relation.subclass": sub_cls,
                    },
                    rationale=resp[:150],
                )
            )
            continue

        # 4. Atributos
        m_attr = re.search(
            r"(?:para\s+la\s+clase\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+).*?recomiendo\s+(?:los\s+)?(?:siguientes\s+)?atributos?:?\s*([^?.\n]+))",
            resp,
            re.IGNORECASE,
        )
        if not m_attr:
            m_attr = re.search(
                r"(?:recomiendo\s+(?:los\s+)?(?:siguientes\s+)?atributos?:?\s*([^?.\n]+)\s+(?:a|para)\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+))",
                resp,
                re.IGNORECASE,
            )
            if m_attr:
                attr_text = m_attr.group(1).strip()
                target_cls = m_attr.group(2).strip()
            else:
                attr_text = None
                target_cls = None
        else:
            target_cls = m_attr.group(1).strip()
            attr_text = m_attr.group(2).strip()

        if target_cls and attr_text:
            clean_attrs = [
                re.sub(r"\([^)]*\)", "", a).strip(" `\n\t")
                for a in re.split(r",|\by\b", attr_text)
                if a.strip(" `\n\t")
            ]
            if not clean_attrs or not all(re.fullmatch(r"[^\W\d]\w*", name) for name in clean_attrs):
                continue
            names = ", ".join(clean_attrs)
            proposals.append(
                Proposal(
                    action="CREATE_ATTRIBUTE",
                    slots={
                        "attribute.target_class": target_cls,
                        "attribute.name": names,
                    },
                    rationale=resp[:150],
                )
            )
    return proposals


class DialogManager:
    """Orquestador central del diálogo continuo con gestión por frames y slots."""

    def __init__(
        self,
        *,
        continuation_repository: AgentContinuationRepository | None = None,
        conversation_reader: AgentConversationReader | None = None,
        ai_provider: AiProvider | None = None,
        context_assembler: ContextAssembler | None = None,
        turn_interpreter: TurnInterpreter | None = None,
        dialog_policy: DialogPolicy | None = None,
        grounded_recommendations: GroundedRecommendationPort | None = None,
    ) -> None:
        self.continuation_repository = continuation_repository
        self.conversation_reader = conversation_reader
        self.ai_provider = ai_provider
        self.context_assembler = context_assembler or ContextAssembler()
        self.turn_interpreter = turn_interpreter or TurnInterpreter(ai_provider=ai_provider)
        self.dialog_policy = dialog_policy or DialogPolicy()
        self.grounded_recommendations = grounded_recommendations

    async def handle_turn(
        self,
        *,
        message: AgentMessage,
        summary_context: str = "",
        max_recent_turns: int = 3,
    ) -> DialogTurnResult:
        """Procesa el turno actual aplicando ensamblado L0..L2, interpretación y política."""
        candidates: list[AgentContinuation] = []
        if self.continuation_repository is not None:
            if message.root_message_id is not None:
                claimed = self.continuation_repository.find_active_by_scope(
                    project_id=message.project_id, user_id=message.user_id
                )
                if (
                    claimed is not None
                    and claimed.root_message_id == message.root_message_id
                    and claimed.state is ContinuationState.CLAIMED
                    and claimed.claimed_by_message_id == message.id
                ):
                    return DialogTurnResult(
                        status="ready_to_execute",
                        effective_request=claimed.effective_request,
                        continuation=claimed,
                        dialog_state=DialogState.from_dict(claimed.dialog_state) if claimed.dialog_state else None,
                    )
            candidates = self.continuation_repository.list_active_candidates(
                project_id=message.project_id,
                user_id=message.user_id,
                purpose=ContinuationPurpose.CLARIFICATION,
                limit=3,
            )

        active_candidate: AgentContinuation | None = candidates[0] if candidates else None

        # Expira candidatos antiguos o duplicados para no dejar pendientes obsoletos
        if len(candidates) > 1 and self.continuation_repository is not None:
            for stale_candidate in candidates[1:]:
                try:
                    self.continuation_repository.save(stale_candidate.expire())
                except Exception as exc:
                    logger.warning("No se pudo expirar continuación obsoleta %s: %s", stale_candidate.id, exc)

        # 1. Cargar o instanciar DialogState (L0)
        dialog_state: DialogState
        if active_candidate is not None and active_candidate.dialog_state:
            dialog_state = DialogState.from_dict(active_candidate.dialog_state)
        elif active_candidate is not None:
            dialog_state = DialogState()
            # Restaurar frame básico a partir de resolved_facts si existen
            frame = DialogFrame(id=str(uuid4())[:8], action="CREATE_RELATION")
            for fact in active_candidate.resolved_facts:
                if isinstance(fact, dict) and "key" in fact and "value" in fact:
                    frame.set_slot(fact["key"], fact["value"])
            frame.evaluate_readiness()
            dialog_state.add_frame(frame)
        else:
            dialog_state = DialogState()

        # 2. Ensamblar contexto multicapa (L0..L2)
        recent_exchanges = []
        max_recent_turns = min(3, max(1, max_recent_turns))
        if (
            active_candidate is None
            and self.conversation_reader is not None
            and message.image_url is None
            and not is_explicit_diagram_question(message.prompt)
            and may_reference_recent_exchange(message.prompt, has_image=message.image_url is not None)
        ):
            recent_exchanges = self.conversation_reader.get_recent_exchanges(
                project_id=message.project_id,
                user_id=message.user_id,
                exclude_message_id=message.id,
                before=message.created_at,
                limit=max_recent_turns,
                exclude_superseded=True,
            )
        assembled_context = self.context_assembler.assemble(
            dialog_state=dialog_state,
            recent_exchanges=recent_exchanges,
            summary_context=summary_context,
            max_recent_turns=max_recent_turns,
        )
        # Una confirmación implícita solo puede referirse al intercambio más reciente.
        if recent_exchanges and assembled_context.recent_turns:
            latest = max(recent_exchanges, key=lambda exchange: (exchange.created_at, exchange.message_id))
            if str(latest.message_id) == assembled_context.recent_turns[-1]["message_id"]:
                dialog_state.proposals.extend(extract_proposals_from_recent_exchanges([latest]))

        # 3. Interpretar el turno del usuario
        if message.image_url is not None:
            turn = InterpretedTurn(user_act="new_request", proposed_action="UNKNOWN")
        else:
            turn = await self.turn_interpreter.interpret(
                user_message=message.prompt,
                dialog_state=dialog_state,
                context=assembled_context,
            )
            if (
                turn.user_act == "new_request"
                and turn.proposed_action in {"UNKNOWN", "CREATE_CLASS"}
                and classify_agent_intent(message.prompt).requires_mutation
            ):
                relation = _RELATION_START.search(message.prompt)
                if relation:
                    remainder = message.prompt[relation.start():]
                    next_command = _NEXT_COMMAND.search(remainder, relation.end() - relation.start())
                    relation_text = remainder[:next_command.start()] if next_command else remainder
                    frame = DialogFrame(id="preflight", action="CREATE_RELATION")
                    relation_slots = self.turn_interpreter.relation_slots_from_request(relation_text)
                    for key, value in relation_slots.items():
                        frame.set_slot(key, value)
                    if not frame.is_ready:
                        before = re.sub(
                            r"(?:\s+y\s+)?(?:luego|despu[eé]s|adem[aá]s)?\s*"
                            r"(?:quiero\s+que\s*)?$",
                            "",
                            message.prompt[:relation.start()],
                            flags=re.IGNORECASE,
                        ).strip(" ,.;")
                        after = remainder[next_command.end():].strip(" ,.;") if next_command else ""
                        other_request = "\n".join(part for part in (before, after) if part)
                        turn = InterpretedTurn(
                            user_act="new_request",
                            proposed_action="CREATE_RELATION",
                            slots={key: value.value for key, value in frame.slots.items()},
                            additional_request=other_request or None,
                            raw_message=message.prompt,
                        )

        if turn.user_act == "read_only":
            same_relation_advice = (
                active_candidate is not None
                and _consult_matches_active_relation(message.prompt, dialog_state.active_frame)
                and re.search(r"\b(?:relaci[oó]n|cardinalidad)\b", message.prompt, re.IGNORECASE)
                and re.search(r"\b(?:sugier|recomiend|aconsej)", message.prompt, re.IGNORECASE)
            )
            if same_relation_advice:
                turn = InterpretedTurn(user_act="consult", raw_message=message.prompt)
            else:
                if active_candidate is not None and self.continuation_repository is not None:
                    self.continuation_repository.save(
                        active_candidate.close(ContinuationCloseReason.TOPIC_CHANGE)
                    )
                logger.info("[Fase 2 · Diálogo] Análisis de solicitud (message_id=%s, route=read_only)", message.id)
                return DialogTurnResult(
                    status="ready_read_only", effective_request=message.prompt
                )

        # Una recomendación con destino propio abre otro objetivo, incluso si había
        # una aclaración pendiente sobre una entidad distinta.
        if (
            turn.user_act == "consult"
            and active_candidate is not None
            and _has_independent_consult_target(message.prompt)
            and not _consult_matches_active_relation(message.prompt, dialog_state.active_frame)
        ):
            if self.continuation_repository is not None:
                self.continuation_repository.save(
                    active_candidate.close(ContinuationCloseReason.TOPIC_CHANGE)
                )
            active_candidate = None
            dialog_state = DialogState()

        # Si la intención es una nueva solicitud autosuficiente o un reintento explícito:
        if turn.user_act in ("retry", "new_request") and (
            turn.user_act == "retry" or turn.proposed_action == "UNKNOWN"
            or (turn.proposed_action == "CREATE_CLASS" and turn.slots.get("class.name"))
        ):
            closed = None
            if turn.user_act != "retry" and active_candidate is not None and self.continuation_repository is not None:
                closed = active_candidate.close(ContinuationCloseReason.TOPIC_CHANGE)
                self.continuation_repository.save(closed)
            logger.info(
                "[Fase 2 · Diálogo] Análisis de solicitud (message_id=%s, route=%s)",
                message.id,
                "retry" if turn.user_act == "retry" else "new_objective",
            )
            return DialogTurnResult(
                status="pass_through",
                effective_request=turn.raw_message or message.prompt,
                intent=turn.proposed_action or "RETRY",
                rationale=turn.rationale,
                continuation=closed,
            )

        if turn.user_act == "new_request":
            dialog_state = DialogState()
        # 4. Decidir siguiente acción con la política
        decision = self.dialog_policy.decide(turn=turn, state=dialog_state)
        if (
            self.grounded_recommendations is not None
            and decision.assistant_act == "consult_with_proposal"
            and decision.proposal is not None
            and decision.proposal.action in {"CREATE_ATTRIBUTE", "CREATE_RELATION"}
        ):
            # La política determinista identifica el alcance; la recomendación
            # concreta se obtiene de la clase actual y reemplaza la sugerencia fija.
            if dialog_state.proposals and dialog_state.proposals[-1] is decision.proposal:
                dialog_state.proposals.pop()
            if decision.proposal.action == "CREATE_ATTRIBUTE":
                target = decision.proposal.slots.get("attribute.target_class")
                if isinstance(target, str) and target.strip():
                    decision = await self.grounded_recommendations.suggest_attributes(
                        project_id=message.project_id,
                        user_id=message.user_id,
                        class_name=target,
                        user_prompt=message.prompt,
                        state=dialog_state,
                    )
            else:
                source = decision.proposal.slots.get("relation.source_class")
                target = decision.proposal.slots.get("relation.target_class")
                if isinstance(source, str) and isinstance(target, str):
                    decision = await self.grounded_recommendations.suggest_relation(
                        project_id=message.project_id,
                        user_id=message.user_id,
                        source_name=source,
                        target_name=target,
                        user_prompt=message.prompt,
                        state=dialog_state,
                    )
        # 4.5. Validación semántica de relaciones antes de autorizar ejecución
        if decision.assistant_act == "fulfill":
            for frame in dialog_state.frames:
                if frame.action == "CREATE_RELATION":
                    s_slot = frame.slots.get("relation.source_class")
                    t_slot = frame.slots.get("relation.target_class")
                    r_slot = frame.slots.get("relation.type")
                    if s_slot and t_slot:
                        is_valid, err_msg = validate_relation_semantics(
                            source=str(s_slot.value),
                            target=str(t_slot.value),
                            rel_type=str(r_slot.value) if r_slot else None,
                        )
                        if not is_valid:
                            decision = PolicyDecision(
                                assistant_act="disambiguate",
                                assistant_message=f"No se puede realizar la relación: {err_msg}",
                                updated_state=dialog_state,
                            )
                            break

        logger.info(
            "[Fase 2 · Diálogo] Análisis de solicitud (message_id=%s, route=%s, missing_fields=%s)",
            message.id,
            decision.assistant_act,
            sum(len(frame.missing_slots) for frame in dialog_state.frames),
        )
        if decision.assistant_message:
            logger.info(
                "[Fase 2 · Diálogo] Respuesta/pregunta de diálogo para el usuario: %s",
                decision.assistant_message.strip(),
            )

        # 5. Persistencia y CAS
        return self._apply_persistence(
            message=message,
            turn=turn,
            decision=decision,
            active_candidate=active_candidate,
            dialog_state=dialog_state,
            context=assembled_context,
        )

    def _apply_persistence(
        self,
        *,
        message: AgentMessage,
        turn: InterpretedTurn,
        decision: PolicyDecision,
        active_candidate: AgentContinuation | None,
        dialog_state: DialogState,
        context: AssembledDialogContext | None = None,
    ) -> DialogTurnResult:
        turns_tuple = tuple(context.recent_turns) if context and context.recent_turns else None
        if self.continuation_repository is None:
            return DialogTurnResult(
                status="ready_to_execute" if decision.assistant_act == "fulfill" else "awaiting_input",
                effective_request=decision.resolved_request,
                assistant_message=decision.assistant_message,
                assistant_act=decision.assistant_act,
                dialog_state=dialog_state,
                recent_turns=turns_tuple,
            )

        # A. Cancelación / Decline / Abandono
        if decision.assistant_act == "decline":
            closed_cand = None
            if active_candidate is not None:
                reason = (
                    ContinuationCloseReason.ABANDONED
                    if turn.user_act == "abandon" or turn.thread_effect == "abandon"
                    else ContinuationCloseReason.DECLINED
                )
                closed_cand = active_candidate.decline(reason=reason)
                closed_cand.dialog_state = dialog_state.to_dict()
                self.continuation_repository.save(closed_cand)
            return DialogTurnResult(
                status="declined",
                assistant_message=decision.assistant_message,
                assistant_act="decline",
                continuation=closed_cand or active_candidate,
                dialog_state=dialog_state,
            )

        # Desambiguación sin candidato activo y sin marcos estructurados: pedir precisión sin abrir un hilo nuevo
        if decision.assistant_act == "disambiguate" and active_candidate is None and not dialog_state.frames:
            return DialogTurnResult(
                status="awaiting_input",
                assistant_message=decision.assistant_message,
                assistant_act="disambiguate",
                dialog_state=dialog_state,
            )

        # B. Pregunta al usuario o propuesta intermedia
        if decision.assistant_act in ("elicit_slots", "consult_with_proposal", "disambiguate"):
            missing_dicts = [
                {"key": s.key, "action": s.action, "critical": s.critical, "question": s.question, "frame_id": frame.id}
                for frame in dialog_state.frames
                for s in frame.missing_slots
            ]
            resolved_dicts = [
                {"key": k, "value": v.value, "frame_id": frame.id}
                for frame in dialog_state.frames
                for k, v in frame.slots.items()
            ]
            if len(resolved_dicts) > MAX_ACTIVE_FACTS or len(missing_dicts) > MAX_ACTIVE_QUESTIONS:
                return DialogTurnResult(
                    status="awaiting_input",
                    assistant_act="disambiguate",
                    assistant_message="¿Puedes dividir la solicitud en grupos más pequeños para aclarar los detalles?",
                )

            if active_candidate is not None and turn.user_act != "new_request":
                active_candidate.dialog_state = dialog_state.to_dict()
                active_candidate.resolved_facts = tuple(resolved_dicts)
                active_candidate.missing_fields = tuple(missing_dicts)
                active_candidate.latest_message_id = message.id
                active_candidate.state = ContinuationState.AWAITING_INPUT
                active_candidate.outcome = ContinuationOutcome.AWAITING_INPUT
                self.continuation_repository.save(active_candidate)
                persisted = active_candidate
            else:
                if active_candidate is not None:
                    closed = active_candidate.close(ContinuationCloseReason.TOPIC_CHANGE)
                    self.continuation_repository.save(closed)
                persisted = AgentContinuation.create(
                    id=uuid4(),
                    project_id=message.project_id,
                    user_id=message.user_id,
                    root_message_id=message.id,
                    effective_request=message.prompt,
                    resolved_facts=resolved_dicts,
                    missing_fields=missing_dicts,
                    outcome=ContinuationOutcome.AWAITING_INPUT,
                    dialog_state=dialog_state.to_dict(),
                    recent_message_ids=[message.id],
                )
                persisted.state = ContinuationState.AWAITING_INPUT
                self.continuation_repository.save(persisted)

            auth_mode = "read_only" if decision.assistant_act == "consult_with_proposal" else None
            return DialogTurnResult(
                status="awaiting_input",
                assistant_message=decision.assistant_message,
                assistant_act=decision.assistant_act,
                continuation=persisted,
                dialog_state=dialog_state,
                authorized_mode=auth_mode,
            )

        # C. Completado / Fulfill
        if decision.assistant_act == "fulfill":
            claimed_candidate = None
            if active_candidate is not None:
                if turn.user_act == "new_request":
                    self.continuation_repository.save(active_candidate.close(ContinuationCloseReason.TOPIC_CHANGE))
                else:
                    claimed_candidate = self.continuation_repository.claim_atomic(
                        continuation_id=active_candidate.id,
                        expected_version=active_candidate.version,
                        by_message_id=message.id,
                    )
                    if claimed_candidate is None:
                        return DialogTurnResult(
                            status="awaiting_input",
                            assistant_act="disambiguate",
                            assistant_message="La solicitud pendiente cambió. ¿Puedes indicar qué deseas hacer?",
                        )
                    claimed_candidate.dialog_state = dialog_state.to_dict()
                    claimed_candidate.effective_request = decision.resolved_request or message.prompt
                    claimed_candidate.latest_message_id = message.id
                    self.continuation_repository.save(claimed_candidate)

            return DialogTurnResult(
                status="ready_to_execute",
                effective_request=decision.resolved_request,
                assistant_message=decision.assistant_message,
                assistant_act="fulfill",
                continuation=claimed_candidate,
                dialog_state=dialog_state,
                recent_turns=turns_tuple,
            )

        return DialogTurnResult(status="pass_through")
