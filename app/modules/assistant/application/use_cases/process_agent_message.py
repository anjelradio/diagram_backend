import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, is_dataclass, replace
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    AgentConversationReader,
)
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
    ResolutionDecision,
    may_reference_recent_exchange,
)
from app.modules.assistant.application.services.continuation.recent_conversation_evidence import (
    RecentConversationEvidenceBuilder,
)
from app.modules.assistant.application.services.continuation.request_readiness import (
    RequestReadiness,
    ReadinessReport,
)
from app.modules.assistant.application.services.continuation.residual_plan_builder import (
    ResidualPlanBuilder,
    UnreconciledOperationException,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.application.services.planning.agent_orchestrator import AgentOrchestrator
from app.modules.assistant.application.services.context_builder import (
    ContextBuilder,
    update_agent_context,
)
from app.modules.assistant.application.services.agent_trace import trace_agent_message
from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.services.execution.agent_response import (
    sanitize_markdown_response,
)
from app.modules.assistant.application.services.execution.terminal_failure import (
    DomainFailureCategory,
)
from app.modules.assistant.application.services.memory_evidence import (
    extract_confirmed_operations,
)
from app.modules.assistant.application.services.memory_updater import MemoryUpdater
from app.modules.assistant.application.services.visual.visual_clarification import (
    adapt_visual_clarification_to_continuation,
    is_explicit_deletion_confirmation,
    is_valid_visual_clarification,
)
from app.modules.assistant.application.ports.agent_completion_publisher import AgentCompletionPublisher
from app.modules.assistant.application.ports.agent_activity_publisher import AgentActivityCode
from app.modules.assistant.application.ports.agent_author_name_reader import AgentAuthorNameReader
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import (
    AgentMessagePersistenceException,
    AgentContextException,
    AgentMemoryCompactionException,
    AgentProcessingException,
    AiProviderError,
    AiProviderUnavailableException,
    InvalidExecutionPlanException,
)
from app.modules.assistant.domain.repositories.agent_continuation_repository import (
    AgentContinuationRepository,
)
from app.modules.assistant.domain.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from app.modules.assistant.domain.repositories.agent_user_memory_repository import (
    AgentUserMemoryRepository,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.core.config import settings
from app.modules.assistant.application.services.dialog.dialog_manager import DialogManager
from app.modules.assistant.application.services.dialog.turn_interpreter import (
    starts_independent_class_request,
)
from app.modules.assistant.application.services.intent import (
    MetamodelGateKind,
    SemanticCategory,
    SemanticIntentRouter,
    SemanticTurnDecision,
    check_metamodel_gate,
)
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    is_neon_sync_prompt,
)
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.application.ports import UnitOfWork

from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionIntegrationProvider,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.enums.notion_task_status import (
    NotionTaskStatus,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)

logger = logging.getLogger(__name__)

_EXPLICIT_RETRY_PATTERN = re.compile(
    r"\b(?:reintenta\w*|reintentar|reanuda\w*|reanudar|contin[uú]a(?:\s+con)?|sigue(?:\s+con)?)\b",
    re.IGNORECASE,
)

_ORDINAL_MAP: dict[str, int] = {
    "primera": 0, "primero": 0, "primer": 0, "1": 0, "1ra": 0, "1ro": 0, "1era": 0, "1ero": 0,
    "segunda": 1, "segundo": 1, "2": 1, "2da": 1, "2do": 1,
    "tercera": 2, "tercero": 2, "tercer": 2, "3": 2, "3ra": 2, "3ro": 2,
    "cuarta": 3, "cuarto": 3, "4": 3, "4ta": 3, "4to": 3,
    "quinta": 4, "quinto": 4, "5": 4, "5ta": 4, "5to": 4,
    "última": -1, "ultima": -1, "último": -1, "ultimo": -1,
}


def _is_notion_related_prompt(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if "notion" in clean:
        return True
    if re.search(r"\b(?:tareas?\s+de\s+notion|pendientes?\s+de\s+notion|tareas?\s+en\s+notion)\b", clean):
        return True
    return False


def _is_neon_related_prompt(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if "neon" in clean:
        return True
    if re.search(r"\b(?:despliega|desplegar|migra|migrar|sincroniza|sincronizar)\s+(?:la\s+)?(?:bd|base\s+de\s+datos|postgres|postgresql)\b", clean):
        return True
    return False


def _is_direct_neon_mutation_bypass_attempt(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if not any(term in clean for term in ("neon", "base de datos", "bd", "postgres", "postgresql")):
        return False
    mutation_verbs = r"\b(?:elimina(?:r)?|borra(?:r)?|quita(?:r)?|modifica(?:r)?|altera(?:r)?|cambia(?:r)?|drop|alter)\b"
    db_targets = r"\b(?:tabla|tablas|columna|columnas|campo|campos|table|tables|column|columns)\b"
    neon_mentions = r"\b(?:en\s+neon|de\s+neon|en\s+la\s+base\s+de\s+datos|en\s+la\s+bd|en\s+postgres|en\s+postgresql)\b"
    return bool(re.search(f"{mutation_verbs}.*{db_targets}.*{neon_mentions}", clean)) or bool(re.search(f"{mutation_verbs}.*{neon_mentions}.*{db_targets}", clean))


def _is_multiple_notion_tasks_request(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if not ("notion" in clean or "tarea" in clean or "pendiente" in clean):
        return False
    patterns = [
        r"\b(?:todas|todos|cada\s+una)\b",
        r"\b(?:varias|m[uú]ltiples)\b",
        r"\b(?:ambas|los\s+dos|las\s+dos)\b",
        r"\b(?:tareas?\s+\d+\s+y\s+\d+)\b",
        r"\b(?:tarea\s+\w+\s+y\s+tarea)\b",
    ]
    is_execution = bool(re.search(
        r"\b(?:haz|hacer|ejecuta(?:r)?|aplica(?:r)?|realiza(?:r)?|procesa(?:r)?|implementa(?:r)?)\b",
        clean,
    ))
    return is_execution and any(re.search(p, clean) for p in patterns)


def _is_single_notion_task_execution_request(
    prompt: str,
    recent_turns: list[dict[str, Any]] | None = None,
) -> bool:
    clean = prompt.strip().casefold()
    if _is_multiple_notion_tasks_request(prompt):
        return False
    has_exec_verb = bool(re.search(
        r"\b(?:ejecuta(?:r)?|haz|hacer|aplica(?:r)?|realiza(?:r)?|procesa(?:r)?|implementa(?:r)?)\b",
        clean,
    ))
    has_task_ref = bool(re.search(
        r"\b(?:tarea|tareas|notion|pendiente|pendientes)\b",
        clean,
    ))
    if not has_task_ref and recent_turns:
        has_cached_tasks = any(
            isinstance(t, dict) and t.get("notion_tasks")
            for t in recent_turns
        )
        if has_cached_tasks and any(re.search(r"\b" + re.escape(w) + r"\b", clean) for w in _ORDINAL_MAP):
            has_task_ref = True

    has_crud_verb = bool(re.search(
        r"\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|elimina(?:r)?|borra(?:r)?|quita(?:r)?|lista(?:r)?|muestra(?:r)?|ver|modifica(?:r)?|cambia(?:r)?|actualiza(?:r)?|cancela(?:r)?)\b",
        clean,
    ))
    return has_exec_verb and has_task_ref and not has_crud_verb


def _is_mixed_diagram_and_notion_request(
    prompt: str,
    recent_turns: list[dict[str, Any]] | None = None,
) -> bool:
    clean = prompt.strip().casefold()
    if not ("notion" in clean or re.search(r"\b(?:tareas?\s+de\s+notion|pendientes?\s+de\s+notion)\b", clean)):
        return False

    if _is_single_notion_task_execution_request(prompt, recent_turns=recent_turns):
        return False

    if re.search(r"^(?:s[ií]|dale|hazlo|procede|adelante)\b", clean):
        last_turn = recent_turns[-1] if recent_turns else {}
        last_assistant = str(last_turn.get("assistant") or last_turn.get("content") or "").casefold()
        offered_canvas_changes = any(phrase in last_assistant for phrase in (
            "en tu lienzo", "en tu diagrama", "estos cambios", "estas relaciones", "estos atributos", "esta clase"
        ))
        if offered_canvas_changes and ("notion" in clean or "tarea" in clean):
            return True

    diagram_mutation_patterns = [
        r"\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|elimina(?:r)?|borra(?:r)?|modifica(?:r)?|relaciona(?:r)?|conecta(?:r)?)\b.*?\b(?:clase|clases|atributo|atributos|relaci[oó]n|relaciones|tabla|tablas|lienzo)\b",
        r"\b(?:clase|clases|atributo|atributos|relaci[oó]n|relaciones|tabla|tablas|lienzo)\b.*?\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|elimina(?:r)?|borra(?:r)?|modifica(?:r)?|relaciona(?:r)?|conecta(?:r)?)\b",
    ]
    notion_action_patterns = [
        r"\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|haz|hacer|pon|guarda(?:r)?|lista(?:r)?|dime|muestra|ver|elimina(?:r)?|actualiza(?:r)?)\b.*?\bnotion\b",
        r"\bnotion\b.*?\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?|haz|hacer|pon|guarda(?:r)?|lista(?:r)?|dime|muestra|ver|elimina(?:r)?|actualiza(?:r)?)\b",
    ]
    has_diagram_mutation = any(re.search(p, clean) for p in diagram_mutation_patterns)
    has_notion_action = any(re.search(p, clean) for p in notion_action_patterns)
    has_compound_connector = bool(re.search(
        r"\b(?:y\s+adem[aá]s|adem[aá]s|y\s+tambi[eé]n|tambi[eé]n|y\s+luego|al\s+mismo\s+tiempo|despu[eé]s)\b",
        clean,
    ))

    if has_diagram_mutation and has_notion_action and has_compound_connector:
        return True

    if re.search(r"\b(?:crea|agrega|a[ñn]ade|guarda)\s+(?:una\s+)?tarea\s+(?:en|de)\s+notion\b", clean):
        if not has_compound_connector:
            return False

    return False


def _is_explicit_retry(prompt: str) -> bool:
    clean = prompt.strip().casefold()
    if clean in {
        "reintenta", "reintentar", "continúa", "continua", "sigue", "reanuda", "reanudar",
        "dale", "hazlo", "sí", "si", "por favor", "adelante", "procede",
    }:
        return True
    return bool(_EXPLICIT_RETRY_PATTERN.search(clean))


def _extract_retry_additional_request(prompt: str) -> str | None:
    cleaned = re.sub(
        r"^(?:reintenta\w*|reintentar|contin[uú]a(?:\s+con)?|sigue(?:\s+con)?|reanuda\w*)"
        r"(?:\s+(?:lo\s+pendiente|el\s+plan|la\s+ejecuci[oó]n|el\s+fallo))?"
        r"(?:\s+(?:y\s+adem[aá]s|y|adem[aá]s|pero))?\s*",
        "",
        prompt.strip(),
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or None


_CONTEXT_DEPENDENT_INDICATORS = re.compile(
    r"\b(?:esa|ese|esos|esas|eso|est[ae]s?|con[eé]cta(?:las|los)?|relaci[oó]na(?:las|los)?|"
    r"aplica(?:r|lo|la|los|las)?|implementa(?:r|lo|la|los|las)?|haz(?:lo)?|dale|"
    r"cancela(?:r)?|olv[ií]da(?:lo)?|descarta(?:r)?|dejalo\s+as[ií]|d[eé]jalo\s+as[ií]|"
    r"sugerencia[s]?|recomendaci[oó]n(?:es)?|propuesta[s]?|"
    r"lo\s+(?:anterior|dicho|sugerido|propuesto|recomendado|acordado)|"
    r"y\s+(?:adem[aá]s|luego|despu[eé]s))\b|"
    r"[¿?]",
    re.IGNORECASE,
)

_AMBIGUOUS_RELATION_WITHOUT_TARGETS = re.compile(
    r"^\s*(?:relaciona(?:r)?|conecta(?:r)?|haz\s+(?:una\s+)?relaci[oó]n|crea\s+(?:una\s+)?relaci[oó]n)\s+"
    r"(?:las\s+clases|clases)?\s*$",
    re.IGNORECASE,
)

_DOMAIN_REASONING_OR_MUTATION_PATTERNS = re.compile(
    r"\b(?:relaci[oó]n|relaciona(?:r|las|los)?|asocia(?:r|ci[oó]n)?|composici[oó]n|agregaci[oó]n|"
    r"herencia|generalizaci[oó]n|vincula(?:r)?|conecta(?:r|las|los)?|"
    r"atributo[s]?|campo[s]?)\b",
    re.IGNORECASE,
)

_CONFIRM_PATTERN = re.compile(
    r"^(?:si\b|ok\b|okay\b|yes\b|dale\b|hazlo\b|procede\b|adelante\b|vale\b|claro\b|perfecto\b|de acuerdo\b|confirmo\b|me parece bien\b)",
    re.IGNORECASE,
)


def _needs_semantic_context_resolution(
    prompt: str,
    has_recent_turns: bool,
    has_active_continuation: bool,
) -> bool:
    if has_active_continuation:
        return True
    clean = prompt.strip()
    if not clean:
        return True
    if _CONTEXT_DEPENDENT_INDICATORS.search(clean):
        return True
    if _AMBIGUOUS_RELATION_WITHOUT_TARGETS.search(clean):
        return True
    if _is_notion_related_prompt(clean):
        return True
    if starts_independent_class_request(clean):
        return False
    if is_neon_sync_prompt(clean):
        if _CONFIRM_PATTERN.search(clean):
            return True
        return False
    if has_recent_turns:
        if _DOMAIN_REASONING_OR_MUTATION_PATTERNS.search(clean):
            return True
        if _CONFIRM_PATTERN.search(clean):
            return True
        return False
    if _DOMAIN_REASONING_OR_MUTATION_PATTERNS.search(clean):
        return True
    return False


@dataclass(frozen=True, slots=True)
class ProcessedAgentMessage:
    message_id: UUID
    project_id: UUID
    status: str
    image_url: str | None
    response_markdown: str | None


class ProcessAgentMessageUseCase:
    """Procesa un mensaje activo sin mantener una transacción durante la red."""

    def __init__(
        self,
        *,
        message_repository: AgentMessageRepository,
        memory_repository: AgentUserMemoryRepository | None,
        project_access_policy: ProjectAccessPolicy,
        context_builder: ContextBuilder,
        orchestrator: AgentOrchestrator,
        uow: UnitOfWork,
        completion_publisher: AgentCompletionPublisher | None = None,
        activity_reporter: Callable[[AgentActivityCode], Awaitable[None]] | None = None,
        author_profile_reader: AgentAuthorNameReader | None = None,
        memory_updater: MemoryUpdater | None = None,
        continuation_repository: AgentContinuationRepository | None = None,
        continuation_resolver: ContinuationResolver | None = None,
        request_readiness: RequestReadiness | None = None,
        conversation_reader: AgentConversationReader | None = None,
        dialog_manager: DialogManager | None = None,
        semantic_intent_router: SemanticIntentRouter | None = None,
        class_provider: Callable[[UUID], dict[str, str]] | None = None,
        class_attributes_provider: Callable[[UUID], dict[str, list[str]]] | None = None,
        integration_repository: ProjectIntegrationRepository | None = None,
        notion_provider: NotionIntegrationProvider | None = None,
        crypto_service: IntegrationCryptoService | None = None,
    ) -> None:
        self.message_repository = message_repository
        self.memory_repository = memory_repository
        self.continuation_repository = continuation_repository
        self.continuation_resolver = continuation_resolver
        self.request_readiness = request_readiness or RequestReadiness()
        self.conversation_reader = conversation_reader
        self.dialog_manager = dialog_manager
        self.semantic_intent_router = semantic_intent_router
        self.class_provider = class_provider
        self.class_attributes_provider = class_attributes_provider
        self.integration_repository = integration_repository
        self.notion_provider = notion_provider
        self.crypto_service = crypto_service
        self.project_access_policy = project_access_policy
        self.context_builder = context_builder
        self.orchestrator = orchestrator
        self.uow = uow
        self.completion_publisher = completion_publisher
        self.activity_reporter = activity_reporter
        self.author_profile_reader = author_profile_reader
        self.memory_updater = memory_updater

    @trace_agent_message
    async def execute(
        self,
        *,
        message_id: UUID,
        project_id: UUID | None = None,
        user_id: str | None = None,
    ) -> ProcessedAgentMessage:
        message = self.message_repository.find_by_id(message_id)
        if message is None:
            raise ProjectNotFoundException()
        if project_id is None:
            project_id = message.project_id
        if user_id is None:
            user_id = message.user_id

        try:
            self.project_access_policy.ensure_read_access(project_id, user_id)
        except ProjectNotFoundException:
            await self._fail_if_running(message_id, project_id, user_id)
            raise

        if (
            message.project_id != project_id
            or message.user_id != user_id
        ):
            raise ProjectNotFoundException()
        if message.status is not AgentMessageStatus.RUNNING:
            return self._to_result(message)

        logger.info(
            "[Fase 1 · Entrada] Mensaje del usuario: %r (message_id=%s, project_id=%s, has_image=%s)",
            message.prompt,
            message_id,
            project_id,
            message.image_url is not None,
        )
        if message.image_url:
            logger.info(
                "[Fase 1 · Entrada] Imagen adjunta del usuario: %s",
                message.image_url,
            )
        await self._report_activity(AgentActivityCode.PREPARING_CONTEXT)
        self.uow.rollback()
        claimed_continuation: AgentContinuation | None = None
        try:
            context = None
            immediate_result = None

            context, immediate_result = self._resolve_visual_clarification(message)

            if immediate_result is None and context is None and _is_multiple_notion_tasks_request(message.prompt):
                immediate_result = AiResult(
                    text=(
                        "Solo puedo ejecutar una tarea de Notion a la vez para mantener la coherencia del diagrama. "
                        "Por favor, selecciona una única tarea para comenzar."
                    ),
                    model_role=ModelRole.MAIN,
                    model="notion_policy",
                    completed=True,
                    metadata={"kind": "notion_policy", "outcome": "rejected_multiple_tasks"},
                )

            if immediate_result is None and context is None and _is_mixed_diagram_and_notion_request(message.prompt):
                immediate_result = AiResult(
                    text=(
                        "He detectado que solicitas tanto modificaciones en el diagrama como acciones en Notion. "
                        "Para mantener la coherencia y el orden en tu proyecto, estas acciones deben gestionarse por separado. "
                        "¿Deseas que primero aplique los cambios en el lienzo o que primero gestione la tarea en Notion?"
                    ),
                    model_role=ModelRole.MAIN,
                    model="notion_policy",
                    completed=True,
                    metadata={"kind": "notion_policy", "outcome": "mixed_diagram_and_notion_rejected"},
                )

            # T009: Pre-flight check para solicitudes relacionadas con Notion
            if immediate_result is None and context is None and _is_notion_related_prompt(message.prompt):
                immediate_result = self._check_notion_integration_readiness(message.project_id)

            # Pre-flight check para solicitudes relacionadas con Neon
            if immediate_result is None and context is None and _is_neon_related_prompt(message.prompt):
                immediate_result = self._check_neon_integration_readiness(
                    message.project_id,
                    message.user_id,
                    message.prompt,
                )

            if immediate_result is None and context is None and message.image_url is None:
                context, immediate_result = self._check_pre_plan_metamodel_gate(message)

            if immediate_result is None and context is None and self.semantic_intent_router is not None and message.image_url is None:
                context, immediate_result, claimed_continuation = await self._route_with_semantic_router(message)

            if immediate_result is None and context is None and self.continuation_repository is not None:
                context, immediate_result, claimed_continuation = await self._handle_continuation(message)

            if immediate_result is not None:
                ai_result = immediate_result
            else:
                if context is None:
                    context = self.context_builder.build(message)
                if getattr(context, "recent_turns", None) is None:
                    raw_exchanges = self._get_recent_exchanges(message, limit=8)
                    if raw_exchanges:
                        recent_turns_list = [
                            {
                                "message_id": str(ex.message_id),
                                "user": ex.user_prompt,
                                "assistant": ex.assistant_response,
                                **({"confirmed_operations": list(ex.confirmed_operations)} if ex.confirmed_operations else {}),
                            }
                            for ex in reversed(raw_exchanges)
                            if not getattr(ex, "is_superseded", False)
                        ]
                        context = update_agent_context(context, recent_turns=recent_turns_list)
                if getattr(context, "existing_classes", None) is None and self.class_provider is not None:
                    try:
                        known_classes = self.class_provider(message.project_id) or {}
                        if known_classes:
                            context = update_agent_context(context, existing_classes=known_classes)
                    except Exception as exc:
                        logger.warning("No se pudieron cargar las clases existentes para el contexto: %s", exc)
                logger.info(
                    "[Fase 3 · Contexto] Contexto preparado (message_id=%s, memory_tokens=%s, "
                    "requires_compaction=%s, has_image=%s)",
                    message_id,
                    getattr(context, "estimated_memory_tokens", None),
                    getattr(context, "requires_compaction", False),
                    getattr(context, "image_url", None) is not None,
                )
                self.uow.rollback()
                respond_with_progress = getattr(
                    self.orchestrator, "respond_with_progress", None
                )
                if callable(respond_with_progress):
                    await self._report_activity(AgentActivityCode.ANALYZING_PROMPT)
                    ai_result = await respond_with_progress(
                        context,
                        lambda plan: self._persist_plan_progress(message, plan),
                        self._report_activity,
                    )
                else:
                    ai_result = await self.orchestrator.respond(context)
            if not isinstance(ai_result.text, str) or not ai_result.text.strip():
                raise AgentProcessingException()
            self.project_access_policy.ensure_read_access(project_id, user_id)
        except ProjectNotFoundException:
            await self._persist_failure(message_id, project_id, user_id, claimed_continuation)
            raise
        except Exception as exc:
            if isinstance(exc, InvalidExecutionPlanException):
                logger.warning(
                    "Falló el procesamiento del mensaje del asistente "
                    "(message_id=%s, error_type=%s, plan_reason=%s)",
                    message_id,
                    type(exc).__name__,
                    exc.reason.value,
                )
            elif isinstance(exc, AiProviderError):
                logger.warning(
                    "Falló el procesamiento del mensaje del asistente "
                    "(message_id=%s, error_type=%s, provider_reason=%s)",
                    message_id,
                    type(exc).__name__,
                    exc.reason.value,
                )
            elif isinstance(exc, AiProviderUnavailableException):
                logger.warning(
                    "Falló el procesamiento del mensaje del asistente "
                    "(message_id=%s, error_type=%s, provider_reason=%s, http_status=%s)",
                    message_id,
                    type(exc).__name__,
                    exc.reason.value,
                    exc.status_code,
                )
            elif isinstance(exc, SQLAlchemyError):
                database_error = getattr(exc, "orig", exc)
                sqlstate = (
                    getattr(database_error, "sqlstate", None)
                    or getattr(database_error, "pgcode", None)
                    or "unknown"
                )
                logger.warning(
                    "Falló el procesamiento del mensaje del asistente "
                    "(message_id=%s, error_type=%s, database_error_type=%s, "
                    "sqlstate=%s, database_detail=%s)",
                    message_id,
                    type(exc).__name__,
                    type(database_error).__name__,
                    sqlstate,
                    _safe_database_error_detail(database_error),
                )
            else:
                logger.warning(
                    "Falló el procesamiento del mensaje del asistente (message_id=%s, error_type=%s: %s)",
                    message_id,
                    type(exc).__name__,
                    exc,
                )
            return await self._persist_failure(message_id, project_id, user_id, claimed_continuation)

        try:
            await self._report_activity(AgentActivityCode.FINALIZING)
            if ai_result.metadata is not None:
                message.plan = ai_result.metadata
            sanitized_text = sanitize_markdown_response(ai_result.text)
            outcome_val = None
            if isinstance(ai_result.metadata, dict):
                outcome_val = ai_result.metadata.get("outcome")

            is_terminal_failure = (
                isinstance(ai_result.metadata, dict)
                and ai_result.metadata.get("kind") == "terminal_domain_failure"
            )
            is_partial = outcome_val == "partial" or (
                isinstance(ai_result.metadata, dict)
                and ai_result.metadata.get("status") == "partial"
            )

            if is_terminal_failure:
                current_msg = self.message_repository.find_by_id(message_id)
                if current_msg and current_msg.status == AgentMessageStatus.CANCELLED:
                    return self._to_result(current_msg)

                message.fail(sanitized_text)
                if self.continuation_repository is not None:
                    has_remaining = any(
                        t.get("status") in {"failed", "blocked"}
                        for t in (
                            getattr(message.plan, "tasks", [])
                            if hasattr(message.plan, "tasks")
                            else (message.plan or {}).get("tasks", [])
                        )
                    )
                    has_applied = any(
                        e.get("status") == "applied"
                        for e in (
                            getattr(message.plan, "operation_ledger", [])
                            if hasattr(message.plan, "operation_ledger")
                            else (message.plan or {}).get("operation_ledger", [])
                        )
                    )
                    suggests_creation = bool(
                        isinstance(ai_result.metadata, dict)
                        and ai_result.metadata.get("suggests_creation")
                    )
                    target_cls = (
                        (ai_result.metadata.get("target_class") or ai_result.metadata.get("missing_class") or "")
                        if isinstance(ai_result.metadata, dict)
                        else ""
                    )

                    if has_remaining and (has_applied or claimed_continuation is not None):
                        root_id = claimed_continuation.root_message_id if claimed_continuation else message.id
                        effective_req = (
                            claimed_continuation.effective_request
                            if claimed_continuation
                            else message.prompt
                        )
                        if suggests_creation and target_cls:
                            effective_req = f"Crear la clase {target_cls} y proceder con: {effective_req}"
                        new_partial_cont = AgentContinuation.create(
                            id=uuid4(),
                            project_id=message.project_id,
                            user_id=message.user_id,
                            root_message_id=root_id,
                            source_plan_message_id=message.id,
                            effective_request=effective_req,
                            outcome=ContinuationOutcome.AWAITING_INPUT if suggests_creation else ContinuationOutcome.PARTIAL,
                            purpose=ContinuationPurpose.CLARIFICATION if suggests_creation else ContinuationPurpose.RESIDUAL_RETRY,
                            missing_fields=(),
                        )
                        self.continuation_repository.save(new_partial_cont)
                    elif suggests_creation:
                        root_id = claimed_continuation.root_message_id if claimed_continuation else message.id
                        base_req = (
                            claimed_continuation.effective_request
                            if claimed_continuation
                            else message.prompt
                        )
                        effective_req = f"Crear la clase {target_cls} y proceder con: {base_req}" if target_cls else base_req
                        new_creation_cont = AgentContinuation.create(
                            id=uuid4(),
                            project_id=message.project_id,
                            user_id=message.user_id,
                            root_message_id=root_id,
                            source_plan_message_id=message.id,
                            effective_request=effective_req,
                            outcome=ContinuationOutcome.AWAITING_INPUT,
                            purpose=ContinuationPurpose.CLARIFICATION,
                            missing_fields=(),
                        )
                        self.continuation_repository.save(new_creation_cont)
                    if claimed_continuation is not None:
                        self.continuation_repository.resolve_atomic(
                            continuation_id=claimed_continuation.id,
                            expected_version=claimed_continuation.version,
                            outcome=ContinuationOutcome.PARTIAL,
                            close_reason=ContinuationCloseReason.FAILED,
                        )

                if not self.message_repository.save_terminal(message):
                    current_msg = self.message_repository.find_by_id(message_id)
                    if current_msg and current_msg.status == AgentMessageStatus.CANCELLED:
                        return self._to_result(current_msg)
                    raise AgentMessagePersistenceException()
                self.uow.commit()
                logger.warning(
                    "Mensaje del asistente finalizado por fallo terminal de dominio "
                    "(message_id=%s, category=%s, element_type=%s, has_confirmed_changes=%s)",
                    message.id,
                    ai_result.metadata.get("category"),
                    ai_result.metadata.get("affected_element_type"),
                    ai_result.metadata.get("has_confirmed_changes"),
                )
            elif is_partial:
                current_msg = self.message_repository.find_by_id(message_id)
                if current_msg and current_msg.status == AgentMessageStatus.CANCELLED:
                    return self._to_result(current_msg)

                message.partial(sanitized_text)
                if self.continuation_repository is not None:
                    root_id = claimed_continuation.root_message_id if claimed_continuation else message.id
                    effective_req = (
                        claimed_continuation.effective_request
                        if claimed_continuation
                        else message.prompt
                    )
                    tasks = (
                        getattr(message.plan, "tasks", [])
                        if hasattr(message.plan, "tasks")
                        else (message.plan or {}).get("tasks", [])
                    )
                    missing_cls = None
                    for t in tasks:
                        if t.get("status") in {"failed", "blocked"} and "class_not_found" in (t.get("error_code") or "").lower():
                            missing_cls = t.get("target_class")
                            if not missing_cls:
                                reason = t.get("failure_reason") or ""
                                m = re.search(r"\*\*([^*]+)\*\*", reason)
                                if m:
                                    missing_cls = m.group(1)
                            if missing_cls:
                                break
                    suggests_creation = False
                    if missing_cls:
                        suggests_creation = True
                        effective_req = f"Crear la clase {missing_cls} y proceder con: {effective_req}"

                    new_partial_cont = AgentContinuation.create(
                        id=uuid4(),
                        project_id=message.project_id,
                        user_id=message.user_id,
                        root_message_id=root_id,
                        source_plan_message_id=message.id,
                        effective_request=effective_req,
                        outcome=ContinuationOutcome.AWAITING_INPUT if suggests_creation else ContinuationOutcome.PARTIAL,
                        purpose=ContinuationPurpose.CLARIFICATION if suggests_creation else ContinuationPurpose.RESIDUAL_RETRY,
                        missing_fields=(),
                    )
                    self.continuation_repository.save(new_partial_cont)
                    if claimed_continuation is not None:
                        self.continuation_repository.resolve_atomic(
                            continuation_id=claimed_continuation.id,
                            expected_version=claimed_continuation.version,
                            outcome=ContinuationOutcome.PARTIAL,
                            close_reason=ContinuationCloseReason.FAILED,
                        )

                if not self.message_repository.save_terminal(message):
                    current_msg = self.message_repository.find_by_id(message_id)
                    if current_msg and current_msg.status == AgentMessageStatus.CANCELLED:
                        return self._to_result(current_msg)
                    raise AgentMessagePersistenceException()
                self.uow.commit()
                logger.info(
                    "[Fin] Mensaje del asistente finalizado con resultado parcial (message_id=%s). Respuesta entregada: %s",
                    message.id,
                    sanitized_text.strip(),
                )
            else:
                if ai_result.completed or outcome_val == "awaiting_input":
                    message.complete(sanitized_text)
                    if claimed_continuation is not None and self.continuation_repository is not None:
                        self.continuation_repository.resolve_atomic(
                            continuation_id=claimed_continuation.id,
                            expected_version=claimed_continuation.version,
                            outcome=ContinuationOutcome.SUCCESS,
                            close_reason=ContinuationCloseReason.RESOLVED,
                        )
                    plan_outcome = message.plan.get("outcome") if isinstance(message.plan, dict) else None
                    is_awaiting = plan_outcome == "awaiting_input" or outcome_val == "awaiting_input"
                    is_declined = plan_outcome == "declined" or outcome_val == "declined"
                else:
                    message.fail(sanitized_text)
                    if claimed_continuation is not None and self.continuation_repository is not None:
                        self.continuation_repository.resolve_atomic(
                            continuation_id=claimed_continuation.id,
                            expected_version=claimed_continuation.version,
                            outcome=ContinuationOutcome.PARTIAL,
                            close_reason=ContinuationCloseReason.FAILED,
                        )
                if not self.message_repository.save_terminal(message):
                    raise AgentMessagePersistenceException()
                self.uow.commit()
        except Exception as exc:
            self.uow.rollback()
            raise AgentMessagePersistenceException() from exc
        await self._publish_finished(message)
        logger.info(
            "[Fin] Procesamiento del asistente finalizado (message_id=%s, status=%s). Respuesta entregada: %s",
            message_id,
            message.status.value,
            sanitized_text.strip(),
        )
        return self._to_result(message)

    def _get_recent_exchanges(
        self,
        message: AgentMessage,
        limit: int = 8,
    ) -> Sequence[Any]:
        if self.conversation_reader is None:
            return ()
        cached = getattr(message, "_cached_recent_exchanges", None)
        if cached is not None:
            return cached
        try:
            exchanges = self.conversation_reader.get_recent_exchanges(
                project_id=message.project_id,
                user_id=message.user_id,
                exclude_message_id=message.id,
                limit=limit,
            )
            setattr(message, "_cached_recent_exchanges", exchanges)
            return exchanges or ()
        except Exception as exc:
            logger.warning("No se pudo cargar el historial reciente: %s", exc)
            return ()

    def _check_pre_plan_metamodel_gate(
        self, message: AgentMessage
    ) -> tuple[AgentContext | None, AiResult | None]:
        existing_classes: dict[str, str] = {}
        if self.class_provider is not None:
            try:
                existing_classes = self.class_provider(message.project_id) or {}
            except Exception as exc:
                logger.warning("No se pudieron obtener las clases existentes para metamodel gate: %s", exc)

        classes_list = (
            list(existing_classes.keys())
            if isinstance(existing_classes, dict)
            else list(existing_classes)
        )

        decision = check_metamodel_gate(message.prompt, existing_classes=classes_list)
        if decision is None:
            return None, None

        if decision.kind == MetamodelGateKind.AMBIGUOUS_RELATION and self.semantic_intent_router is not None:
            return None, None

        logger.info(
            "[Pre-Flight Metamodel Gate] Solicitud interceptada deterministamente (kind=%s, prompt=%r, message_id=%s)",
            decision.kind.value,
            message.prompt,
            message.id,
        )

        if decision.requires_input:
            if self.continuation_repository is not None:
                new_cont = AgentContinuation.create(
                    id=uuid4(),
                    project_id=message.project_id,
                    user_id=message.user_id,
                    root_message_id=message.id,
                    source_plan_message_id=message.id,
                    effective_request=f"Metamodelo UML ({decision.kind.value}): {message.prompt}",
                    outcome=ContinuationOutcome.AWAITING_INPUT,
                    purpose=ContinuationPurpose.CLARIFICATION,
                    missing_fields=tuple({"field": f} for f in decision.missing_fields),
                )
                self.continuation_repository.save(new_cont)
                self.uow.commit()

            ai_res = AiResult(
                text=decision.explanation,
                model_role=ModelRole.MAIN,
                model="metamodel_gate",
                completed=True,
                metadata={
                    "kind": "continuation",
                    "outcome": "awaiting_input",
                    "assistant_act": "clarification_question",
                    "gate_kind": decision.kind.value,
                    "target_class": decision.target_class,
                    "related_class": decision.related_class,
                },
            )
            return None, ai_res
        else:
            ai_res = AiResult(
                text=decision.explanation,
                model_role=ModelRole.MAIN,
                model="metamodel_gate",
                completed=True,
                metadata={
                    "kind": "direct_clarification",
                    "outcome": "informational",
                    "assistant_act": "explanation",
                    "gate_kind": decision.kind.value,
                    "target_class": decision.target_class,
                },
            )
            return None, ai_res

    def _check_notion_integration_readiness(self, project_id: UUID) -> AiResult | None:
        if self.integration_repository is None or self.notion_provider is None or self.crypto_service is None:
            return AiResult(
                text="Para utilizar Notion en este proyecto, primero debes activarlo e ingresar tu API Key desde el menú de Integraciones.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
                metadata={"kind": "notion_policy", "outcome": "integration_not_available"},
            )
        integration = self.integration_repository.find_by_project_and_provider(
            project_id,
            IntegrationProvider.NOTION,
        )
        if integration is None or not integration.encrypted_api_key:
            return AiResult(
                text="Para utilizar Notion en este proyecto, primero debes activarlo e ingresar tu API Key desde el menú de Integraciones.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
                metadata={"kind": "notion_policy", "outcome": "unconfigured_api_key"},
            )
        if not integration.is_initialized or not integration.external_database_id:
            return AiResult(
                text="La integración con Notion aún no ha sido inicializada en este proyecto. Por favor, inicialízala desde el menú de Integraciones para comenzar a gestionar tareas.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
                metadata={"kind": "notion_policy", "outcome": "uninitialized_project"},
            )
        return None

    def _check_neon_integration_readiness(
        self,
        project_id: UUID,
        user_id: str,
        prompt: str,
    ) -> AiResult | None:
        # 1. Regla de negocio: Exclusividad absoluta del propietario (OWNER)
        try:
            access_context = self.project_access_policy.resolve_access(project_id, user_id)
            if access_context.access_role != ProjectAccessRole.OWNER:
                return AiResult(
                    text=(
                        "Solo el propietario (creador) del proyecto tiene permisos para desplegar, "
                        "inicializar o sincronizar la infraestructura de base de datos en Neon."
                    ),
                    model_role=ModelRole.MAIN,
                    model="neon_policy",
                    completed=True,
                    metadata={"kind": "neon_policy", "outcome": "owner_permission_required"},
                )
        except Exception:
            pass

        # 2. Regla de negocio: Prohibición de mutación directa en Neon
        if _is_direct_neon_mutation_bypass_attempt(prompt):
            return AiResult(
                text=(
                    "La base de datos en Neon es un espejo automatizado de tu diagrama UML. "
                    "Para realizar cambios en las tablas o columnas de Neon, primero solicita la modificación en el diagrama de clases "
                    "(por ejemplo: 'elimina la clase X' o 'agrega el atributo Y a la clase Z') y luego pide 'despliega esto en Neon' para sincronizarlos."
                ),
                model_role=ModelRole.MAIN,
                model="neon_policy",
                completed=True,
                metadata={"kind": "neon_policy", "outcome": "direct_mutation_bypass_prevented"},
            )

        # 3. Regla de negocio: Configuración previa en Integraciones
        if self.integration_repository is None or self.crypto_service is None:
            return AiResult(
                text="Para utilizar Neon en este proyecto, primero debes ingresar tu API Key desde el menú de Integraciones.",
                model_role=ModelRole.MAIN,
                model="neon_policy",
                completed=True,
                metadata={"kind": "neon_policy", "outcome": "integration_not_available"},
            )

        integration = self.integration_repository.find_by_project_and_provider(
            project_id,
            IntegrationProvider.NEON,
        )
        if integration is None or not integration.encrypted_api_key:
            return AiResult(
                text="Para utilizar Neon en este proyecto, primero debes ingresar tu API Key desde el menú de Integraciones.",
                model_role=ModelRole.MAIN,
                model="neon_policy",
                completed=True,
                metadata={"kind": "neon_policy", "outcome": "unconfigured_api_key"},
            )

        if not integration.is_initialized or not integration.neon_project_id:
            return AiResult(
                text=(
                    "La integración con Neon aún no ha sido inicializada en este proyecto. "
                    "Por favor, inicialízala desde el menú de Integraciones para crear el proyecto y desplegar tu diagrama inicial en Neon."
                ),
                model_role=ModelRole.MAIN,
                model="neon_policy",
                completed=True,
                metadata={"kind": "neon_policy", "outcome": "uninitialized_project"},
            )

        return None

    async def _route_with_semantic_router(
        self, message: AgentMessage
    ) -> tuple[AgentContext | None, AiResult | None, AgentContinuation | None]:
        if self.semantic_intent_router is None:
            return None, None, None

        logger.info(
            "[Fase 2 · Enrutador Semántico] Analizando intención (message_id=%s, project_id=%s)",
            message.id,
            message.project_id,
        )

        raw_exchanges = self._get_recent_exchanges(message, limit=8)
        recent_turns: list[dict[str, Any]] = [
            {
                "message_id": str(ex.message_id),
                "user": ex.user_prompt,
                "assistant": ex.assistant_response,
                **({"notion_tasks": list(ex.notion_tasks)} if getattr(ex, "notion_tasks", None) else {}),
                **({"confirmed_operations": list(ex.confirmed_operations)} if getattr(ex, "confirmed_operations", None) else {}),
            }
            for ex in reversed(raw_exchanges)
            if not getattr(ex, "is_superseded", False)
        ]

        existing_classes: dict[str, str] = {}
        if self.class_provider is not None:
            try:
                existing_classes = self.class_provider(message.project_id) or {}
            except Exception as exc:
                logger.warning("No se pudieron obtener las clases existentes: %s", exc)

        existing_class_attributes: dict[str, list[str]] = {}
        if getattr(self, "class_attributes_provider", None) is not None:
            try:
                existing_class_attributes = self.class_attributes_provider(message.project_id) or {}
            except Exception as exc:
                logger.warning("No se pudieron obtener los atributos de las clases existentes: %s", exc)

        active_candidate: AgentContinuation | None = None
        if self.continuation_repository is not None:
            candidates = self.continuation_repository.find_active_candidates(
                project_id=message.project_id,
                user_id=message.user_id,
                limit=1,
            )
            if candidates:
                active_candidate = candidates[0]

        if active_candidate is None and _is_single_notion_task_execution_request(message.prompt, recent_turns=recent_turns):
            n_ctx, n_imm, n_cand = await self._handle_single_notion_task_execution(
                message, recent_turns, existing_classes, existing_class_attributes
            )
            if n_ctx is not None or n_imm is not None:
                return n_ctx, n_imm, n_cand

        if _is_mixed_diagram_and_notion_request(message.prompt, recent_turns=recent_turns):
            return None, AiResult(
                text=(
                    "He detectado que solicitas tanto modificaciones en el diagrama como acciones en Notion. "
                    "Para mantener la coherencia y el orden en tu proyecto, estas acciones deben gestionarse por separado. "
                    "¿Deseas que primero aplique los cambios en el lienzo o que primero gestione la tarea en Notion?"
                ),
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
                metadata={"kind": "notion_policy", "outcome": "mixed_diagram_and_notion_rejected"},
            ), None

        if not _needs_semantic_context_resolution(
            message.prompt,
            has_recent_turns=bool(recent_turns),
            has_active_continuation=active_candidate is not None,
        ):
            # Acción directa autosuficiente sin contexto previo: pasa directamente al planificador
            context = self.context_builder.build(message)
            req_mutation = (
                classify_agent_intent(message.prompt).requires_mutation
                or is_neon_sync_prompt(message.prompt)
            )
            auth_mode = "execute" if req_mutation else "read_only"
            context = update_agent_context(
                context,
                effective_request=message.prompt,
                prompt=message.prompt,
                authorized_mode=auth_mode,
                recent_turns=recent_turns,
                existing_classes=existing_classes,
                existing_class_attributes=existing_class_attributes,
            )
            return context, None, None

        decision = await self.semantic_intent_router.route_turn(
            prompt=message.prompt,
            recent_turns=recent_turns,
            existing_classes=existing_classes,
            existing_class_attributes=existing_class_attributes,
            active_continuation=active_candidate,
        )

        logger.info(
            "[Fase 2 · Enrutador Semántico] Decisión: category=%s, requires_mutation=%s, resolved_goal=%r (reasoning=%s)",
            decision.category.value,
            decision.requires_mutation,
            decision.resolved_goal,
            decision.reasoning,
        )

        if decision.category == SemanticCategory.DECLINE_OR_CANCEL:
            if active_candidate is not None and self.continuation_repository is not None:
                closed_cand = active_candidate.decline(reason=ContinuationCloseReason.DECLINED)
                self.continuation_repository.save(closed_cand)
                self.uow.commit()
            decline_text = (
                decision.clarification_question
                or "Entendido, se ha cancelado la solicitud pendiente. ¿Hay algo más en lo que pueda ayudarte?"
            )
            ai_res = AiResult(
                text=decline_text,
                model_role=ModelRole.MAIN,
                model="semantic_router_decline",
                completed=True,
                metadata={
                    "kind": "continuation",
                    "outcome": "declined",
                    "assistant_act": "decline",
                    "reasoning": decision.reasoning,
                },
            )
            return None, ai_res, None

        if decision.category == SemanticCategory.NEEDS_MORE_CONTEXT:
            active_notion_task = (
                active_candidate.dialog_state.get("active_notion_task")
                if active_candidate and active_candidate.dialog_state
                else None
            )
            dialog_state = {"active_notion_task": active_notion_task} if active_notion_task else None
            if self.continuation_repository is not None:
                if active_candidate is not None:
                    closed = active_candidate.expire(reason=ContinuationCloseReason.EXPIRED)
                    self.continuation_repository.save(closed)
                new_cont = AgentContinuation.create(
                    id=uuid4(),
                    project_id=message.project_id,
                    user_id=message.user_id,
                    root_message_id=active_candidate.root_message_id if active_candidate else message.id,
                    source_plan_message_id=message.id,
                    effective_request=decision.resolved_goal or message.prompt,
                    outcome=ContinuationOutcome.AWAITING_INPUT,
                    purpose=ContinuationPurpose.CLARIFICATION,
                    missing_fields=tuple({"field": f} for f in decision.missing_info),
                    dialog_state=dialog_state,
                )
                self.continuation_repository.save(new_cont)
                self.uow.commit()
            clarification_text = (
                decision.clarification_question
                or "¿Podrías darme más detalles para poder ayudarte?"
            )
            ai_res = AiResult(
                text=clarification_text,
                model_role=ModelRole.MAIN,
                model="semantic_router_clarification",
                completed=True,
                metadata={
                    "kind": "continuation",
                    "outcome": "awaiting_input",
                    "assistant_act": "clarification_question",
                    "missing_info": decision.missing_info,
                    "reasoning": decision.reasoning,
                    **({"active_notion_task": active_notion_task} if active_notion_task else {}),
                },
            )
            return None, ai_res, None

        if decision.category == SemanticCategory.CONCEPTUAL_CONSULTATION:
            context = self.context_builder.build(message)
            effective_request = decision.resolved_goal or message.prompt
            context = update_agent_context(
                context,
                effective_request=effective_request,
                prompt=effective_request,
                authorized_mode="read_only",
                recent_turns=recent_turns,
                existing_classes=existing_classes,
                existing_class_attributes=existing_class_attributes,
                semantic_routed=True,
            )
            return context, None, None

        residual_plan = None
        if (
            active_candidate is not None
            and active_candidate.purpose == ContinuationPurpose.RESIDUAL_RETRY
            and _is_explicit_retry(message.prompt)
            and active_candidate.source_plan_message_id is not None
        ):
            source_msg = self.message_repository.find_by_id(active_candidate.source_plan_message_id)
            if source_msg and source_msg.plan:
                prior_dict = (
                    source_msg.plan.get("prior_execution_plan")
                    if isinstance(source_msg.plan, dict) and "prior_execution_plan" in source_msg.plan
                    else source_msg.plan
                )
                add_req = _extract_retry_additional_request(message.prompt)
                builder = ResidualPlanBuilder()
                try:
                    residual_plan = builder.build(
                        prior_dict,
                        new_goal=active_candidate.effective_request,
                        additional_request=add_req,
                    )
                except Exception as exc:
                    logger.warning("No se pudo construir el plan residual: %s", exc)

        claimed: AgentContinuation | None = None
        if active_candidate is not None and self.continuation_repository is not None:
            claimed = self.continuation_repository.claim_atomic(
                continuation_id=active_candidate.id,
                expected_version=active_candidate.version,
                by_message_id=message.id,
            )
            if claimed is not None and active_candidate.root_message_id is not None:
                message.root_message_id = active_candidate.root_message_id
                if not self.message_repository.link_root_message(
                    message_id=message.id, root_message_id=active_candidate.root_message_id
                ):
                    logger.warning("No se pudo enlazar root_message_id=%s", active_candidate.root_message_id)
            self.uow.commit()

        context = self.context_builder.build(message)
        auth_mode = "execute" if decision.requires_mutation else "read_only"
        effective_request = decision.resolved_goal or message.prompt
        is_compound = decision.category == SemanticCategory.COMPOUND_ACTION
        active_notion_task = (
            active_candidate.dialog_state.get("active_notion_task")
            if active_candidate and active_candidate.dialog_state
            else None
        )
        context = update_agent_context(
            context,
            effective_request=effective_request,
            prompt=effective_request,
            authorized_mode=auth_mode,
            recent_turns=recent_turns,
            is_compound=is_compound,
            existing_classes=existing_classes,
            existing_class_attributes=existing_class_attributes,
            semantic_routed=True,
            active_notion_task=active_notion_task,
            residual_plan=residual_plan,
        )

        return context, None, claimed

    async def _handle_single_notion_task_execution(
        self,
        message: AgentMessage,
        recent_turns: list[dict[str, Any]],
        existing_classes: dict[str, str],
        existing_class_attributes: dict[str, list[str]] | None = None,
    ) -> tuple[AgentContext | None, AiResult | None, AgentContinuation | None]:
        if self.integration_repository is None or self.notion_provider is None or self.crypto_service is None:
            return None, None, None

        integration = self.integration_repository.find_by_project_and_provider(
            message.project_id,
            IntegrationProvider.NOTION,
        )
        if integration is None or not integration.encrypted_api_key:
            return None, AiResult(
                text="Para utilizar Notion en este proyecto, primero debes activarlo e ingresar tu API Key desde el menú de Integraciones.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
            ), None

        if not integration.is_initialized or not integration.external_database_id:
            return None, AiResult(
                text="La integración con Notion aún no ha sido inicializada en este proyecto. Por favor, inicialízala desde el menú de Integraciones para comenzar a gestionar tareas.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
            ), None

        api_key = self.crypto_service.decrypt(integration.encrypted_api_key)
        user_name = "Colaborador"
        if self.author_profile_reader is not None:
            names = self.author_profile_reader.find_names({message.user_id})
            user_name = names.get(message.user_id, "Colaborador")

        tasks: list[dict[str, Any]] = []
        cached_tasks = None
        for turn in recent_turns:
            if turn.get("notion_tasks"):
                cached_tasks = turn["notion_tasks"]
                break

        if cached_tasks:
            for ct in cached_tasks:
                if isinstance(ct, dict) and ct.get("task_id") and ct.get("title"):
                    tasks.append(ct)

        if not tasks:
            task_models = self.notion_provider.list_tasks(
                api_key=api_key,
                database_id=integration.external_database_id,
                assignee_name=user_name,
                status=NotionTaskStatus.PENDING,
            )
            tasks = [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status.value,
                    "priority": t.priority.value,
                    "assignee": t.assignee_name,
                    "due_date": t.due_date,
                    "url": t.url,
                }
                for t in task_models
            ]

        if not tasks:
            return None, AiResult(
                text="No tienes tareas pendientes en Notion para ejecutar.",
                model_role=ModelRole.MAIN,
                model="notion_policy",
                completed=True,
            ), None

        clean = message.prompt.casefold()
        matched_task: dict[str, Any] | None = None

        for ord_word, ord_idx in _ORDINAL_MAP.items():
            if re.search(r"\b" + re.escape(ord_word) + r"\b", clean):
                idx = ord_idx if ord_idx >= 0 else len(tasks) - 1
                if 0 <= idx < len(tasks):
                    matched_task = tasks[idx]
                    break

        if matched_task is None:
            num_match = re.search(r"\b(?:tarea|número|numero|la)?\s*(\d+)\b", clean)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(tasks):
                    matched_task = tasks[idx]

        if matched_task is None:
            quote_match = re.search(r"['\"]([^'\"]+)['\"]", message.prompt)
            if quote_match:
                cand_title = quote_match.group(1).casefold()
                for t in tasks:
                    t_title = t.get("title", "")
                    if cand_title in t_title.casefold() or t_title.casefold() in cand_title:
                        matched_task = t
                        break

        if matched_task is None:
            for t in tasks:
                t_title = t.get("title", "")
                t_words = [w for w in t_title.casefold().split() if len(w) > 3]
                if t_words and any(w in clean for w in t_words):
                    matched_task = t
                    break

        if matched_task is None:
            matched_task = tasks[0]

        task_id = str(matched_task.get("task_id", ""))
        title = str(matched_task.get("title", ""))
        desc = str(matched_task.get("description", "") or "")

        active_task = {
            "task_id": task_id,
            "title": title,
            "description": desc,
        }

        task_instruction = (
            f"{title}. {desc}".strip()
            if desc
            else title.strip()
        )

        if self.semantic_intent_router is not None:
            decision = await self.semantic_intent_router.route_turn(
                prompt=task_instruction,
                recent_turns=(),
                existing_classes=existing_classes,
                existing_class_attributes=existing_class_attributes,
                active_continuation=None,
            )
            if decision.category == SemanticCategory.NEEDS_MORE_CONTEXT:
                if self.continuation_repository is not None:
                    new_cont = AgentContinuation.create(
                        id=uuid4(),
                        project_id=message.project_id,
                        user_id=message.user_id,
                        root_message_id=message.id,
                        source_plan_message_id=message.id,
                        effective_request=decision.resolved_goal or task_instruction,
                        outcome=ContinuationOutcome.AWAITING_INPUT,
                        purpose=ContinuationPurpose.CLARIFICATION,
                        missing_fields=tuple({"field": f} for f in decision.missing_info),
                        dialog_state={"active_notion_task": active_task},
                    )
                    self.continuation_repository.save(new_cont)
                    self.uow.commit()

                return None, AiResult(
                    text=decision.clarification_question or "¿Podrías darme más detalles para poder ejecutar esta tarea en el diagrama?",
                    model_role=ModelRole.MAIN,
                    model="semantic_router_clarification",
                    completed=True,
                    metadata={
                        "kind": "continuation",
                        "outcome": "awaiting_input",
                        "assistant_act": "clarification_question",
                        "missing_info": decision.missing_info,
                        "active_notion_task": active_task,
                    },
                ), None

            effective_goal = decision.resolved_goal or task_instruction
        else:
            effective_goal = task_instruction

        context = self.context_builder.build(message)
        context = update_agent_context(
            context,
            effective_request=effective_goal,
            prompt=effective_goal,
            authorized_mode="execute",
            active_notion_task=active_task,
            recent_turns=recent_turns,
            existing_classes=existing_classes,
            existing_class_attributes=existing_class_attributes,
            semantic_routed=True,
        )
        return context, None, None

    async def _handle_continuation(
        self, message: AgentMessage
    ) -> tuple[AgentContext | None, AiResult | None, AgentContinuation | None]:
        if self.continuation_repository is None:
            return None, None, None

        pass_through_request: str | None = None
        if getattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", False) and self.dialog_manager is not None:
            turn_result = await self.dialog_manager.handle_turn(
                message=message,
                summary_context="",
            )
            if turn_result.continuation is not None:
                root_id = turn_result.continuation.root_message_id
                if root_id != message.id and turn_result.status != "pass_through":
                    message.root_message_id = root_id
            if turn_result.status == "awaiting_input":
                ai_res = AiResult(
                    text=turn_result.assistant_message or "¿Podrías darme más detalles?",
                    model_role=ModelRole.MAIN,
                    model="dialog_manager",
                    completed=True,
                    metadata={
                        "kind": "continuation",
                        "outcome": "awaiting_input",
                        "assistant_act": turn_result.assistant_act,
                        "dialog_state": turn_result.dialog_state.to_dict() if turn_result.dialog_state else None,
                    },
                )
                return None, ai_res, None
            elif turn_result.status == "declined":
                ai_res = AiResult(
                    text=turn_result.assistant_message or "Entendido, se ha cancelado la solicitud pendiente.",
                    model_role=ModelRole.MAIN,
                    model="dialog_manager_decline",
                    completed=True,
                    metadata={
                        "kind": "continuation",
                        "outcome": "declined",
                        "assistant_act": "decline",
                    },
                )
                return None, ai_res, None
            elif turn_result.status in ("ready_to_execute", "ready_read_only"):
                effective_request = turn_result.effective_request or message.prompt
                context = self.context_builder.build(message)
                auth_mode = turn_result.authorized_mode or ("read_only" if turn_result.status == "ready_read_only" else "execute")
                if is_dataclass(context):
                    kw: dict[str, Any] = {"effective_request": effective_request, "prompt": effective_request}
                    if hasattr(context, "authorized_mode"):
                        kw["authorized_mode"] = auth_mode
                    if hasattr(context, "dialog_state") and turn_result.dialog_state:
                        kw["dialog_state"] = turn_result.dialog_state.to_dict()
                    if turn_result.recent_turns:
                        kw["recent_turns"] = list(turn_result.recent_turns)
                    context = replace(context, **kw)
                else:
                    setattr(context, "effective_request", effective_request)
                    setattr(context, "prompt", effective_request)
                    setattr(context, "authorized_mode", auth_mode)
                    if turn_result.dialog_state:
                        setattr(context, "dialog_state", turn_result.dialog_state.to_dict())
                    if turn_result.recent_turns:
                        setattr(context, "recent_turns", list(turn_result.recent_turns))
                if turn_result.continuation is not None and message.root_message_id is not None:
                    if not self.message_repository.link_root_message(
                        message_id=message.id, root_message_id=message.root_message_id
                    ):
                        raise AgentMessagePersistenceException()
                if turn_result.status == "ready_to_execute":
                    self.uow.commit()
                return context, None, turn_result.continuation
            elif turn_result.status == "pass_through":
                if turn_result.intent != "RETRY":
                    if turn_result.continuation is not None:
                        self.uow.commit()
                    if turn_result.effective_request and turn_result.effective_request != message.prompt:
                        context = self.context_builder.build(message)
                        if is_dataclass(context):
                            context = replace(
                                context,
                                effective_request=turn_result.effective_request,
                                prompt=turn_result.effective_request,
                            )
                        else:
                            setattr(context, "effective_request", turn_result.effective_request)
                            setattr(context, "prompt", turn_result.effective_request)
                        return context, None, None
                    return None, None, None
                else:
                    residual_candidates = (
                        self.continuation_repository.list_active_candidates(
                            project_id=message.project_id,
                            user_id=message.user_id,
                            purpose=ContinuationPurpose.RESIDUAL_RETRY,
                            limit=1,
                        )
                        if self.continuation_repository is not None
                        else []
                    )
                    if residual_candidates and _is_explicit_retry(message.prompt):
                        cand = residual_candidates[0]
                        claimed = self.continuation_repository.claim_atomic(
                            continuation_id=cand.id,
                            expected_version=cand.version,
                            by_message_id=message.id,
                        )
                        if claimed is not None and cand.source_plan_message_id is not None:
                            source_msg = self.message_repository.find_by_id(cand.source_plan_message_id)
                            if source_msg and source_msg.plan:
                                prior_dict = (
                                    source_msg.plan.get("prior_execution_plan")
                                    if isinstance(source_msg.plan, dict) and "prior_execution_plan" in source_msg.plan
                                    else source_msg.plan
                                )
                                add_req = _extract_retry_additional_request(message.prompt)
                                builder = ResidualPlanBuilder()
                                try:
                                    residual_plan = builder.build(
                                        prior_dict,
                                        new_goal=cand.effective_request,
                                        additional_request=add_req,
                                    )
                                    if cand.root_message_id is not None:
                                        message.root_message_id = cand.root_message_id
                                    self.uow.commit()
                                    context = self.context_builder.build(message)
                                    auth_mode = turn_result.authorized_mode or "execute"
                                    if is_dataclass(context):
                                        kw = {
                                            "effective_request": cand.effective_request,
                                            "prompt": cand.effective_request,
                                            "residual_plan": residual_plan,
                                        }
                                        if hasattr(context, "authorized_mode"):
                                            kw["authorized_mode"] = auth_mode
                                        context = replace(context, **kw)
                                    else:
                                        setattr(context, "effective_request", cand.effective_request)
                                        setattr(context, "prompt", cand.effective_request)
                                        setattr(context, "residual_plan", residual_plan)
                                        setattr(context, "authorized_mode", auth_mode)
                                    return context, None, claimed
                                except UnreconciledOperationException:
                                    ai_res = AiResult(
                                        text="No se puede continuar automáticamente porque una operación previa quedó en estado incierto. Por favor revisa el diagrama.",
                                        model_role=ModelRole.MAIN,
                                        model="continuation",
                                        completed=True,
                                    )
                                    return None, ai_res, None

                    return None, None, None

        candidates = self.continuation_repository.find_active_candidates(
            project_id=message.project_id,
            user_id=message.user_id,
            limit=3,
        )

        effective_request = pass_through_request or message.prompt
        recent_resolution = None
        may_reference_history = may_reference_recent_exchange(
            message.prompt, has_image=message.image_url is not None
        )
        raw_exchanges: Sequence[Any] = ()
        if candidates or (may_reference_history and self.conversation_reader is not None):
            recent_evidence = None
            if may_reference_history and self.conversation_reader is not None:
                builder = RecentConversationEvidenceBuilder()
                raw_exchanges = self._get_recent_exchanges(message, limit=8)
                if (
                    not candidates
                    and message.image_url is None
                    and any(exchange.kind == "visual_clarification" for exchange in raw_exchanges)
                ):
                    return None, None, None
                recent_evidence = builder.build_evidence(raw_exchanges)

            resolver = self.continuation_resolver or ContinuationResolver()
            resolution = await resolver.resolve(
                user_prompt=message.prompt,
                candidates=candidates,
                recent_messages=recent_evidence,
                image_url=message.image_url,
            )

            if resolution.decision == ResolutionDecision.RECENT_FOLLOW_UP and resolution.effective_request:
                effective_request = resolution.effective_request
                recent_resolution = resolution

            if resolution.decision == ResolutionDecision.FOLLOW_UP and resolution.candidate_id:
                candidate = next((c for c in candidates if c.id == resolution.candidate_id), None)
                if candidate:
                    # 1. Revalidar pertenencia de la continuación
                    if candidate.project_id != message.project_id or candidate.user_id != message.user_id:
                        ai_res = AiResult(
                            text="No se puede continuar esta solicitud porque pertenece a otro ámbito.",
                            model_role=ModelRole.MAIN,
                            model="continuation",
                            completed=True,
                        )
                        return None, ai_res, None

                    # 2. Revalidar permisos sobre el proyecto
                    try:
                        self.project_access_policy.ensure_read_access(message.project_id, message.user_id)
                    except (ProjectNotFoundException, Exception):
                        ai_res = AiResult(
                            text="No tienes permisos para acceder a este proyecto.",
                            model_role=ModelRole.MAIN,
                            model="continuation",
                            completed=True,
                        )
                        return None, ai_res, None

                    merged_facts = self.request_readiness.merge_facts(
                        list(candidate.resolved_facts), resolution.resolved_facts
                    )
                    effective_request = resolution.effective_request or candidate.effective_request
                    additional_request = next(
                        (fact["value"] for fact in merged_facts
                         if fact["key"] == "continuation.additional_request"),
                        None,
                    )
                    if resolution.additional_request:
                        additional_request = "\n".join(
                            filter(None, (additional_request, resolution.additional_request))
                        )
                        merged_facts = self.request_readiness.merge_facts(
                            merged_facts,
                            [{"key": "continuation.additional_request", "value": additional_request}],
                        )
                    combined_missing_map: dict[str, dict[str, Any]] = {}
                    for f in candidate.missing_fields:
                        if "key" in f:
                            combined_missing_map[f["key"]] = dict(f)
                    for f in resolution.missing_fields:
                        if "key" in f:
                            combined_missing_map[f["key"]] = dict(f)
                    remaining_missing = self.request_readiness.compute_remaining_missing(
                        list(combined_missing_map.values()), merged_facts
                    )
                    critical_missing = [f for f in remaining_missing if f.get("critical", False)]

                    if not critical_missing:
                        claimed = self.continuation_repository.claim_atomic(
                            continuation_id=candidate.id,
                            expected_version=candidate.version,
                            by_message_id=message.id,
                            new_message_id=message.id,
                            user_id=message.user_id,
                            project_id=message.project_id,
                        )
                        if claimed is None and not (candidate.image_context and candidate.image_context.get("legacy_message_id")):
                            ai_res = AiResult(
                                text="Esta solicitud ya ha sido atendida en otra respuesta.",
                                model_role=ModelRole.MAIN,
                                model="continuation",
                                completed=True,
                            )
                            return None, ai_res, None

                        # Si proviene de una aclaración visual legacy, reclamar el marcador original para evitar doble claim
                        if candidate.image_context and candidate.image_context.get("legacy_message_id"):
                            claimer = getattr(self.message_repository, "claim_visual_clarification", None)
                            if callable(claimer):
                                legacy_msg_id = UUID(str(candidate.image_context["legacy_message_id"]))
                                claimer(
                                    message_id=legacy_msg_id,
                                    expected_version=1,
                                    continuation_id=message.id,
                                    user_id=message.user_id,
                                    project_id=message.project_id,
                                )
                        self.uow.commit()
                        context = self.context_builder.build(message)
                        residual_plan = None
                        if candidate.source_plan_message_id is not None:
                            source_msg = self.message_repository.find_by_id(candidate.source_plan_message_id)
                            if source_msg and source_msg.plan:
                                prior_dict = (
                                    source_msg.plan.get("prior_execution_plan")
                                    if isinstance(source_msg.plan, dict) and "prior_execution_plan" in source_msg.plan
                                    else source_msg.plan
                                )
                                builder = ResidualPlanBuilder()
                                try:
                                    residual_plan = builder.build(
                                        prior_dict,
                                        new_goal=effective_request,
                                        additional_request=additional_request,
                                    )
                                except UnreconciledOperationException:
                                    ai_res = AiResult(
                                        text="No se puede continuar automáticamente porque una operación previa quedó en estado incierto. Por favor revisa el diagrama.",
                                        model_role=ModelRole.MAIN,
                                        model="continuation",
                                        completed=True,
                                    )
                                    return None, ai_res, None

                        if is_dataclass(context):
                            context_kwargs: dict[str, Any] = {
                                "effective_request": effective_request,
                                "prompt": effective_request,
                                "residual_plan": residual_plan,
                            }
                            if candidate.image_context:
                                marker = candidate.image_context
                                deletion_confirmed = (
                                    is_explicit_deletion_confirmation(message.prompt)
                                    if marker.get("requires_deletion_confirmation")
                                    else False
                                )
                                selected_class_ids = dict(marker.get("selected_class_ids") or {})
                                ambiguity = marker.get("class_ambiguity")
                                if ambiguity and isinstance(ambiguity, dict) and "candidate_ids" in ambiguity:
                                    cand_ids = [str(c) for c in ambiguity.get("candidate_ids", [])]
                                    chosen = [c for c in cand_ids if c in message.prompt.casefold()]
                                    if len(chosen) == 1:
                                        selected_class_ids[ambiguity.get("class_name", "").strip().casefold()] = chosen[0]

                                context_kwargs.update(
                                    prompt=marker.get("original_prompt", effective_request),
                                    image_url=marker.get("image_url"),
                                    visual_clarification_answer=message.prompt,
                                    visual_clarification_context=marker,
                                    visual_deletion_confirmed=deletion_confirmed,
                                    visual_selected_class_ids=selected_class_ids or None,
                                )
                            context = replace(context, **context_kwargs)
                        else:
                            setattr(context, "effective_request", effective_request)
                            setattr(context, "prompt", effective_request)
                            setattr(context, "residual_plan", residual_plan)
                        return context, None, claimed or candidate
                    else:
                        updated_candidate = candidate.apply_clarification(
                            new_effective_request=effective_request,
                            resolved_facts=merged_facts,
                            remaining_missing_fields=remaining_missing,
                            latest_message_id=message.id,
                        )
                        self.continuation_repository.save(updated_candidate)
                        self.uow.commit()
                        question = self.request_readiness.format_grouped_question(remaining_missing) or "¿Podrías indicar los datos faltantes?"
                        ai_res = AiResult(
                            text=question,
                            model_role=ModelRole.MAIN,
                            model="continuation-readiness",
                            completed=True,
                            metadata={"kind": "continuation", "outcome": "awaiting_input"},
                        )
                        return None, ai_res, None

            elif resolution.decision == ResolutionDecision.DECLINE:
                candidate = next((c for c in candidates if c.id == resolution.candidate_id), candidates[0] if len(candidates) == 1 else None)
                if candidate:
                    declined = candidate.decline()
                    self.continuation_repository.save(declined)
                    self.uow.commit()
                ai_res = AiResult(
                    text="Entendido, se ha cancelado la solicitud pendiente.",
                    model_role=ModelRole.MAIN,
                    model="continuation-decline",
                    completed=True,
                )
                return None, ai_res, None

            elif resolution.decision == ResolutionDecision.AMBIGUOUS:
                ai_res = AiResult(
                    text=resolution.ambiguity_message or "¿A qué cambio o solicitud te refieres?",
                    model_role=ModelRole.MAIN,
                    model="continuation-ambiguous",
                    completed=True,
                )
                return None, ai_res, None

        # Solicitud inicial: comprobar si faltan campos críticos
        if recent_resolution is None:
            report = self.request_readiness.evaluate_initial_request(effective_request)
        else:
            missing = self.request_readiness.compute_remaining_missing(
                recent_resolution.missing_fields, recent_resolution.resolved_facts
            )
            report = ReadinessReport(
                is_ready=not any(field.get("critical") for field in missing),
                missing_fields=missing,
                resolved_facts=recent_resolution.resolved_facts,
                grouped_question=self.request_readiness.format_grouped_question(missing),
            )
        if report is not None and not report.is_ready:
            existing_candidates = self.continuation_repository.list_active_candidates(
                project_id=message.project_id,
                user_id=message.user_id,
                limit=5,
            )
            for old_c in existing_candidates:
                try:
                    self.continuation_repository.save(old_c.expire())
                except Exception as exc:
                    logger.warning("No se pudo expirar continuación previa: %s", exc)

            initial_dialog_state = None
            if getattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", False):
                d_state = DialogState()
                action_kind = "CREATE_RELATION"
                if any("attribute" in f.get("key", "") for f in report.resolved_facts + report.missing_critical_fields):
                    action_kind = "CREATE_ATTRIBUTE"
                d_frame = DialogFrame(id=str(uuid4())[:8], action=action_kind)
                for fact in report.resolved_facts:
                    if isinstance(fact, dict) and "key" in fact and "value" in fact:
                        d_frame.set_slot(fact["key"], fact["value"])
                d_frame.evaluate_readiness()
                d_state.add_frame(d_frame)
                initial_dialog_state = d_state.to_dict()

            new_continuation = AgentContinuation.create(
                id=uuid4(),
                project_id=message.project_id,
                user_id=message.user_id,
                root_message_id=message.id,
                effective_request=effective_request,
                resolved_facts=report.resolved_facts,
                missing_fields=report.missing_critical_fields,
                dialog_state=initial_dialog_state,
            )
            self.continuation_repository.save(new_continuation)
            self.uow.commit()
            question = report.grouped_question or "¿Podrías especificar los datos que faltan?"
            ai_res = AiResult(
                text=question,
                model_role=ModelRole.MAIN,
                model="continuation-readiness",
                completed=True,
                metadata={"kind": "continuation", "outcome": "awaiting_input"},
            )
            return None, ai_res, None

        if recent_resolution is not None:
            context = self.context_builder.build(message)
            kw: dict[str, Any] = {"prompt": effective_request, "effective_request": effective_request}
            if raw_exchanges:
                kw["recent_turns"] = [
                    {
                        "message_id": str(ex.message_id),
                        "user": ex.user_prompt,
                        "assistant": ex.assistant_response,
                        **({"confirmed_operations": list(ex.confirmed_operations)} if ex.confirmed_operations else {}),
                    }
                    for ex in reversed(raw_exchanges)
                    if not getattr(ex, "is_superseded", False)
                ]
            if is_dataclass(context):
                return replace(context, **kw), None, None
            for k, v in kw.items():
                setattr(context, k, v)
            return context, None, None

        if pass_through_request is not None:
            context = self.context_builder.build(message)
            if is_dataclass(context):
                context = replace(
                    context, prompt=effective_request, effective_request=effective_request
                )
            else:
                setattr(context, "prompt", effective_request)
                setattr(context, "effective_request", effective_request)
            return context, None, None

        return None, None, None

    def _resolve_visual_clarification(self, message: AgentMessage):
        """Reanuda una única aclaración del mismo usuario/proyecto con CAS."""
        if message.image_url is not None or starts_independent_class_request(message.prompt):
            return None, None
        finder = getattr(
            self.message_repository, "find_pending_visual_clarifications", None
        )
        claimer = getattr(self.message_repository, "claim_visual_clarification", None)
        if not callable(finder) or not callable(claimer):
            return None, None
        candidates = finder(user_id=message.user_id, project_id=message.project_id)
        if not candidates or not isinstance(candidates, list):
            return None, None
        valid_candidates = [
            candidate
            for candidate in candidates
            if candidate.project_id == message.project_id
            and candidate.user_id == message.user_id
            and is_valid_visual_clarification(
                candidate.plan,
                user_id=message.user_id,
                project_id=message.project_id,
            )
        ]
        if not valid_candidates:
            return None, AiResult(
                text="La aclaración de la imagen venció o ya no es válida. Envía una nueva solicitud y adjunta la imagen otra vez.",
                model_role=ModelRole.MAIN,
                model="visual-clarification",
                completed=True,
            )
        referenced = [
            candidate
            for candidate in valid_candidates
            if str(candidate.id) in message.prompt
        ]
        if len(referenced) == 1:
            selected = referenced[0]
        elif len(valid_candidates) == 1:
            selected = valid_candidates[0]
        else:
            ids = ", ".join(str(candidate.id) for candidate in valid_candidates[:5])
            return None, AiResult(
                text=(
                    "Hay varias aclaraciones visuales pendientes. Indica el ID del mensaje "
                    f"que quieres continuar ({ids}) o adjunta la imagen de nuevo."
                ),
                model_role=ModelRole.MAIN,
                model="visual-clarification",
                completed=True,
            )
        marker = selected.plan
        selected_class_ids: dict[str, str] | None = None
        ambiguity = marker.get("class_ambiguity")
        if ambiguity is not None:
            previous_selections = marker.get("selected_class_ids", {})
            if (
                not isinstance(ambiguity, dict)
                or not isinstance(ambiguity.get("class_name"), str)
                or not ambiguity["class_name"].strip()
                or not isinstance(ambiguity.get("candidate_ids"), list)
                or not 2 <= len(ambiguity["candidate_ids"]) <= 20
                or not isinstance(previous_selections, dict)
                or len(previous_selections) > 100
                or not all(
                    isinstance(name, str) and isinstance(class_id, str)
                    for name, class_id in previous_selections.items()
                )
            ):
                return None, AiResult(
                    text="La selección anterior ya no es válida. Adjunta la imagen de nuevo.",
                    model_role=ModelRole.MAIN,
                    model="visual-clarification",
                )
            try:
                candidate_ids = [str(UUID(candidate)) for candidate in ambiguity["candidate_ids"]]
                selected_class_ids = {
                    name.strip().casefold(): str(UUID(class_id))
                    for name, class_id in previous_selections.items()
                    if name.strip()
                }
            except (ValueError, TypeError, AttributeError):
                return None, AiResult(
                    text="La selección anterior ya no es válida. Adjunta la imagen de nuevo.",
                    model_role=ModelRole.MAIN,
                    model="visual-clarification",
                )
            selected_ids = [
                candidate for candidate in candidate_ids if candidate in message.prompt.casefold()
            ]
            if len(selected_ids) != 1:
                return None, AiResult(
                    text=(
                        f"Indica exactamente uno de los IDs de la clase {ambiguity['class_name']}: "
                        + ", ".join(candidate_ids)
                    ),
                    model_role=ModelRole.MAIN,
                    model="visual-clarification",
                )
            selected_class_ids[ambiguity["class_name"].strip().casefold()] = selected_ids[0]
        deletion_confirmed = False
        if marker.get("requires_deletion_confirmation") is True:
            deletion_confirmed = is_explicit_deletion_confirmation(message.prompt)
            if not deletion_confirmed:
                if not claimer(
                    message_id=selected.id,
                    expected_version=selected.plan_version,
                    continuation_id=message.id,
                    user_id=message.user_id,
                    project_id=message.project_id,
                ):
                    return None, AiResult(
                        text="La confirmación ya no está disponible. No realicé eliminaciones.",
                        model_role=ModelRole.MAIN,
                        model="visual-clarification",
                        completed=True,
                    )
                self.uow.commit()
                return None, AiResult(
                    text="Entendido. No realicé eliminaciones.",
                    model_role=ModelRole.MAIN,
                    model="visual-clarification",
                    completed=True,
                )
        if not claimer(
            message_id=selected.id,
            expected_version=selected.plan_version,
            continuation_id=message.id,
            user_id=message.user_id,
            project_id=message.project_id,
        ):
            return None, AiResult(
                text="Esta aclaración ya fue utilizada o cambió mientras la respondías. Adjunta la imagen de nuevo para continuar.",
                model_role=ModelRole.MAIN,
                model="visual-clarification",
                completed=True,
            )
        try:
            self.uow.commit()
        except Exception as exc:
            self.uow.rollback()
            raise AgentMessagePersistenceException() from exc
        context = self.context_builder.build(message)
        return replace(
            context,
            prompt=marker["original_prompt"],
            image_url=marker["image_url"],
            visual_clarification_answer=message.prompt,
            visual_clarification_context=marker,
            visual_deletion_confirmed=deletion_confirmed,
            visual_selected_class_ids=selected_class_ids,
        ), None

    async def _persist_plan_progress(
        self, message: AgentMessage, plan: ExecutionPlan
    ) -> None:
        """Confirma cada snapshot del plan mediante comparación optimista."""
        self.uow.rollback()
        latest = self.message_repository.find_by_id(message.id)
        if (
            latest is None
            or latest.status is not AgentMessageStatus.RUNNING
            or latest.project_id != message.project_id
            or latest.user_id != message.user_id
        ):
            raise AgentMessagePersistenceException()
        latest.plan = plan.to_dict()
        if not self.message_repository.save_plan_progress(latest):
            self.uow.rollback()
            raise AgentMessagePersistenceException()
        try:
            self.uow.commit()
        except Exception as exc:
            self.uow.rollback()
            raise AgentMessagePersistenceException() from exc
        message.plan = latest.plan
        message.plan_version = latest.plan_version

    async def _fail_if_running(self, message_id: UUID, project_id: UUID, user_id: str) -> None:
        self.uow.rollback()
        message = self.message_repository.find_by_id(message_id)
        if (
            message is not None
            and message.project_id == project_id
            and message.user_id == user_id
            and message.status is AgentMessageStatus.RUNNING
        ):
            await self._persist_failure(message_id, project_id, user_id)

    async def _compact_and_persist_memory(self, context, user_id: str):
        return context

    async def _update_user_memory(
        self, message: AgentMessage, response_markdown: str
    ) -> None:
        return

    async def _persist_failure(
        self,
        message_id: UUID,
        project_id: UUID,
        user_id: str,
        claimed_continuation: AgentContinuation | None = None,
    ) -> ProcessedAgentMessage:
        self.uow.rollback()
        try:
            failed_message = self.message_repository.find_by_id(message_id)
            if (
                failed_message is None
                or failed_message.project_id != project_id
                or failed_message.user_id != user_id
            ):
                raise AgentMessagePersistenceException()
            if failed_message.status is not AgentMessageStatus.RUNNING:
                raise AgentMessagePersistenceException()
            failed_message.fail()
            if claimed_continuation is not None and self.continuation_repository is not None:
                self.continuation_repository.resolve_atomic(
                    continuation_id=claimed_continuation.id,
                    expected_version=claimed_continuation.version,
                    outcome=ContinuationOutcome.PARTIAL,
                    close_reason=ContinuationCloseReason.FAILED,
                )
            if not self.message_repository.save_terminal(failed_message):
                raise AgentMessagePersistenceException()
            self.uow.commit()
            await self._publish_finished(failed_message)
            return self._to_result(failed_message)
        except Exception as exc:
            self.uow.rollback()
            if isinstance(exc, AgentMessagePersistenceException):
                raise
            raise AgentMessagePersistenceException() from exc

    @staticmethod
    def _to_result(message: AgentMessage) -> ProcessedAgentMessage:
        return ProcessedAgentMessage(
            message_id=message.id,
            project_id=message.project_id,
            status=message.status.value,
            image_url=message.image_url,
            response_markdown=message.response_markdown,
        )

    async def _publish_finished(self, message: AgentMessage) -> None:
        if self.completion_publisher is None:
            return
        try:
            event = dict(
                project_id=message.project_id,
                user_id=message.user_id,
                message_id=message.id,
                prompt=message.prompt,
                image_url=message.image_url,
                status=message.status.value,
                response_markdown=message.response_markdown or "No se recibió respuesta.",
                created_at=message.created_at,
            )
            if self.author_profile_reader is not None:
                profile = self.author_profile_reader.find_profiles({message.user_id}).get(
                    message.user_id
                )
                event.update(
                    author_name=profile.name if profile and profile.name else message.user_id,
                    author_avatar_url=profile.avatar_url if profile else None,
                )
            await self.completion_publisher.publish_finished(**event)
        except Exception:
            logger.exception("No se pudo publicar agent_message_finished para %s", message.id)

    async def _report_activity(self, code: AgentActivityCode) -> None:
        if self.activity_reporter is None:
            return
        try:
            await self.activity_reporter(code)
        except Exception:
            logger.debug("No se pudo reportar actividad del agente (code=%s)", code.value, exc_info=True)



def _is_visual_clarification(metadata) -> bool:
    return isinstance(metadata, dict) and metadata.get("kind") == "visual_clarification"


def _safe_database_error_detail(error: BaseException) -> str:
    """Resume la causa del driver sin registrar sentencias ni parámetros SQL."""
    detail = " ".join(str(error).split())
    return detail[:500] if detail else "unavailable"
