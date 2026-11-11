from uuid import UUID
import asyncio
from uuid import uuid4

from sqlmodel import Session, select

from app.core.config import settings
from app.core.dependencies import get_event_bus
from app.modules.assistant.application.services.diagram import (
    AgentConversationTools,
    DiagramAuditTools,
    DiagramMutationTools,
    DiagramReadTools,
)
from app.modules.assistant.application.services.audit import AuditQueryService
from app.modules.collaboration.infrastructure.persistence.readers.sqlmodel_project_member_list_reader import (
    SQLModelProjectMemberListReader,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_audit_log_repository import (
    SQLModelDiagramAuditLogRepository,
)
from app.modules.assistant.application.services.execution import (
    AgentToolActorContext,
    PlanExecutor,
    ToolRegistry,
)
from app.modules.assistant.application.services.planning import (
    ActionPlanner,
    AgentOrchestrator,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.agent_activity_reporter import AgentActivityReporter
from app.modules.assistant.application.services.context_builder import ContextBuilder
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
)
from app.modules.assistant.application.services.continuation.request_readiness import (
    RequestReadiness,
)
from app.modules.assistant.application.services.memory_compactor import MemoryCompactor
from app.modules.assistant.application.services.memory_updater import MemoryUpdater
from app.modules.assistant.application.services.token_estimator import TokenEstimator
from app.modules.assistant.application.services.dialog.dialog_manager import DialogManager
from app.modules.assistant.application.services.diagram.grounded_recommendation import GroundedRecommendationService
from app.modules.assistant.application.services.intent import SemanticIntentRouter
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.assistant.infrastructure.external.qwen_ai_provider import QwenAiProvider
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_user_memory_repository import (
    SQLModelAgentUserMemoryRepository,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_author_name_reader import (
    SQLModelAgentAuthorNameReader,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_conversation_reader import (
    SQLModelAgentConversationReader,
)
from app.modules.assistant.application.services.integrations.neon_agent_tools import (
    NeonAgentTools,
)
from app.modules.assistant.application.services.integrations.notion_agent_tools import (
    NotionAgentTools,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseUseCase,
)
from app.modules.integrations.infrastructure.external.neon_mcp_provider import (
    NeonMcpProvider,
)
from app.modules.integrations.infrastructure.external.notion_mcp_provider import (
    NotionMcpProvider,
)
from app.modules.integrations.infrastructure.persistence.repositories.sqlmodel_project_integration_repository import (
    SQLModelProjectIntegrationRepository,
)
from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
    AgentReservationEmitter,
)
from app.modules.assistant.infrastructure.realtime.agent_completion_publisher import (
    WebSocketAgentCompletionPublisher,
)
from app.modules.assistant.infrastructure.realtime.agent_activity_publisher import (
    WebSocketAgentActivityPublisher,
)
from app.modules.assistant.infrastructure.realtime.agent_component_reservation_publisher import (
    WebSocketAgentComponentReservationPublisher,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.application.queries.diagram.agent_diagram_queries import (
    AgentDiagramQueryHandler,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_agent_diagram_reader import (
    SQLModelAgentDiagramReader,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def build_process_agent_message_use_case(
    *,
    session: Session,
    project_id: UUID,
    user_id: str,
    message_id: UUID,
    worker_id: str,
    attempt_id: UUID | None = None,
    activity_stopped: asyncio.Event | None = None,
) -> ProcessAgentMessageUseCase:
    """Construye un caso de uso con sesión/UoW propiedad del worker."""
    uow = SqlModelUnitOfWork(session, get_event_bus())
    project_repository = SQLModelProjectRepository(session)
    member_repository = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repository, member_repository)
    message_repository = SQLModelAgentMessageRepository(session, worker_id=worker_id)
    conversation_reader = SQLModelAgentConversationReader(session)
    provider = QwenAiProvider()
    activity_reporter = AgentActivityReporter(
        WebSocketAgentActivityPublisher(),
        project_id=project_id,
        message_id=message_id,
        attempt_id=attempt_id or uuid4(),
        stopped=activity_stopped,
    )
    token_estimator = TokenEstimator()
    tool_registry = ToolRegistry(
        max_arguments_chars=settings.AGENT_MAX_TOOL_ARGUMENTS_CHARS,
        actor_context=AgentToolActorContext(
            project_id=project_id,
            user_id=user_id,
            message_id=message_id,
        ),
    )
    diagram_access = DiagramAccessPolicy(project_repository, member_repository)
    reservation_publisher = WebSocketAgentComponentReservationPublisher()
    reservation_emitter = AgentReservationEmitter(
        reservation_publisher,
        project_id=project_id,
        message_id=message_id,
    )
    diagram_reader = SQLModelAgentDiagramReader(
        session,
        max_detail_items=settings.AGENT_MAX_ELEMENT_DETAIL_ITEMS,
    )
    diagram_query_handler = AgentDiagramQueryHandler(
        access_policy=diagram_access,
        reader=diagram_reader,
    )
    DiagramReadTools(
        diagram_query_handler,
        project_id=project_id,
        user_id=user_id,
        reservation_emitter=reservation_emitter,
        max_result_chars=settings.AGENT_MAX_TOOL_RESULT_CHARS,
    ).register(tool_registry)
    DiagramMutationTools(
        session,
        uow,
        project_id=project_id,
        user_id=user_id,
        reservation_emitter=reservation_emitter,
    ).register(tool_registry)
    author_profile_reader = SQLModelAgentAuthorNameReader(session)
    user_names = author_profile_reader.find_names({user_id})
    current_user_name = user_names.get(user_id, "Colaborador")

    integration_repo = SQLModelProjectIntegrationRepository(session)
    crypto_service = IntegrationCryptoService()
    notion_provider = NotionMcpProvider()
    NotionAgentTools(
        project_id=project_id,
        current_user_name=current_user_name,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        notion_provider=notion_provider,
    ).register(tool_registry)

    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    rel_repo = SQLModelDiagramRelationRepository(session)
    sync_neon_use_case = SyncNeonDatabaseUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        project_repository=project_repository,
        class_repository=class_repo,
        attribute_repository=attr_repo,
        relation_repository=rel_repo,
        crypto_service=crypto_service,
        neon_provider=NeonMcpProvider(),
        uow=uow,
    )
    NeonAgentTools(
        project_id=project_id,
        user_id=user_id,
        sync_neon_use_case=sync_neon_use_case,
    ).register(tool_registry)

    AgentConversationTools(
        conversation_reader=conversation_reader,
        access_policy=access_policy,
        project_id=project_id,
        user_id=user_id,
        max_total_chars=4000,
    ).register(tool_registry)

    audit_repo = SQLModelDiagramAuditLogRepository(session)
    member_list_reader = SQLModelProjectMemberListReader(session)
    audit_query_service = AuditQueryService(
        audit_repository=audit_repo,
        member_reader=member_list_reader,
        project_repository=project_repository,
        author_name_reader=author_profile_reader,
    )
    DiagramAuditTools(
        audit_query_service,
        project_id=project_id,
        user_id=user_id,
    ).register(tool_registry)
    def _provide_classes(proj_id: UUID) -> dict[str, str]:
        res = diagram_reader.search_elements(
            project_id=proj_id, query="", types=("class",), limit=50, offset=0
        )
        return {
            item.name: str(item.id)
            for item in res.items
            if item.element_type == "class" and item.name and item.id
        }

    def _provide_class_attributes(proj_id: UUID) -> dict[str, list[str]]:
        classes = session.exec(
            select(DiagramClassModel)
            .where(
                DiagramClassModel.project_id == proj_id,
                DiagramClassModel.deleted_date.is_(None),
            )
            .order_by(DiagramClassModel.name.asc())
        ).all()
        class_ids = [c.id for c in classes]
        attrs_by_class: dict[UUID, list[str]] = {}
        if class_ids:
            attrs = session.exec(
                select(DiagramAttributeModel)
                .where(
                    DiagramAttributeModel.class_id.in_(class_ids),
                    DiagramAttributeModel.deleted_date.is_(None),
                )
                .order_by(DiagramAttributeModel.position.asc())
            ).all()
            for a in attrs:
                attrs_by_class.setdefault(a.class_id, []).append(a.name)
        return {
            c.name: attrs_by_class.get(c.id, [])
            for c in classes
        }

    prompt_composer = PromptComposer(variant=getattr(settings, "AGENT_PROMPT_VARIANT", "legacy"))
    continuation_repository = SQLModelAgentContinuationRepository(session)
    dialog_manager = None
    if getattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", True):
        dialog_manager = DialogManager(
            continuation_repository=continuation_repository,
            conversation_reader=conversation_reader,
            ai_provider=provider,
            grounded_recommendations=GroundedRecommendationService(
                diagram_query_handler, provider,
            ),
        )
    semantic_intent_router = (
        SemanticIntentRouter(ai_provider=provider) if provider is not None else None
    )
    return ProcessAgentMessageUseCase(
        message_repository=message_repository,
        memory_repository=None,
        continuation_repository=continuation_repository,
        continuation_resolver=ContinuationResolver(
            ai_provider=provider,
            prompt_composer=prompt_composer,
        ),
        request_readiness=RequestReadiness(),
        conversation_reader=conversation_reader,
        dialog_manager=dialog_manager,
        semantic_intent_router=semantic_intent_router,
        class_provider=_provide_classes,
        class_attributes_provider=_provide_class_attributes,
        project_access_policy=access_policy,
        context_builder=ContextBuilder(
            token_estimator=token_estimator,
            max_memory_tokens=settings.AGENT_MEMORY_MAX_TOKENS,
        ),
        integration_repository=integration_repo,
        notion_provider=notion_provider,
        crypto_service=crypto_service,
        orchestrator=AgentOrchestrator(
            provider,
            None,
            action_planner=ActionPlanner(
                provider,
                max_tasks=settings.AGENT_MAX_PLAN_TASKS,
                max_output_tokens=settings.AGENT_PLANNING_MAX_OUTPUT_TOKENS,
                prompt_composer=prompt_composer,
            ),
            plan_executor=PlanExecutor(
                provider,
                tool_registry,
                max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
                max_execution_seconds=settings.AGENT_MAX_EXECUTION_SECONDS,
                task_max_output_tokens=settings.AGENT_TASK_MAX_OUTPUT_TOKENS,
                final_max_output_tokens=settings.AGENT_FINAL_MAX_OUTPUT_TOKENS,
                prompt_composer=prompt_composer,
                fast_synthesis=getattr(settings, "AGENT_FAST_SYNTHESIS_ENABLED", True),
                class_provider=_provide_classes,
            ),
            prompt_composer=prompt_composer,
        ),
        uow=uow,
        completion_publisher=WebSocketAgentCompletionPublisher(),
        activity_reporter=activity_reporter.report,
        author_profile_reader=author_profile_reader,
        memory_updater=None,
    )


