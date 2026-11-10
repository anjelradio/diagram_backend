from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.execution.agent_response import (
    CommunicableFact,
    format_deterministic_response,
    format_plan_execution_response,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    AgentToolActorContext,
    ToolRegistry,
)
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    is_neon_sync_prompt,
)
from app.modules.assistant.application.services.integrations.neon_agent_tools import (
    NeonAgentTools,
)
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
    _is_direct_neon_mutation_bypass_attempt,
    _is_neon_related_prompt,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    PostgresMigrationSummary,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseCommand,
    SyncNeonDatabaseUseCase,
)
from app.modules.integrations.domain.entities.project_integration import (
    ProjectIntegration,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.infrastructure.persistence.repositories.sqlmodel_project_integration_repository import (
    SQLModelProjectIntegrationRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def test_is_neon_related_prompt_detection():
    assert _is_neon_related_prompt("despliega esto en neon") is True
    assert _is_neon_related_prompt("sincroniza la base de datos de postgres") is True
    assert _is_neon_related_prompt("migra la bd a postgresql") is True
    assert _is_neon_related_prompt("actualiza neon") is True
    assert _is_neon_related_prompt("sin croniza la base de datos en neon") is True
    assert _is_neon_related_prompt("Sí, sincroniza nuestro proyecto, a Neon.") is True
    assert _is_neon_related_prompt("crea la clase Producto") is False
    assert _is_neon_related_prompt("agrega un atributo precio") is False

    assert is_neon_sync_prompt("sin croniza la base de datos en neon") is True
    assert is_neon_sync_prompt("Sí, sincroniza nuestro proyecto, a Neon.") is True
    assert is_neon_sync_prompt("sincroniza neon") is True
    assert classify_agent_intent("sin croniza la base de datos en neon").requires_mutation is True
    assert classify_agent_intent("Sí, sincroniza nuestro proyecto, a Neon.").requires_mutation is True


def test_is_direct_neon_mutation_bypass_attempt_detection():
    assert _is_direct_neon_mutation_bypass_attempt("elimina la tabla usuario en neon") is True
    assert _is_direct_neon_mutation_bypass_attempt("borra la columna email en postgres") is True
    assert _is_direct_neon_mutation_bypass_attempt("modifica la tabla cliente en la base de datos") is True
    assert _is_direct_neon_mutation_bypass_attempt("alter table orders en neon") is True
    assert _is_direct_neon_mutation_bypass_attempt("despliega esto en neon") is False
    assert _is_direct_neon_mutation_bypass_attempt("sincroniza neon con el diagrama") is False
    assert _is_direct_neon_mutation_bypass_attempt("elimina la clase usuario") is False


def test_neon_preflight_checks(session: Session):
    owner_id = f"owner-{uuid4().hex[:6]}"
    editor_id = f"collab-{uuid4().hex[:6]}"

    session.add(BetterAuthUser(id=owner_id, name="Owner", email="owner@test.com", emailVerified=True, createdAt=datetime.now(timezone.utc), updatedAt=datetime.now(timezone.utc)))
    session.add(BetterAuthUser(id=editor_id, name="Editor", email="editor@test.com", emailVerified=True, createdAt=datetime.now(timezone.utc), updatedAt=datetime.now(timezone.utc)))

    project = ProjectModel(name="Store API", owner_id=owner_id)
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(ProjectMemberModel(project_id=project.id, user_id=editor_id, role="EDITOR", status="ACTIVE"))
    session.commit()

    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    crypto_service = IntegrationCryptoService(secret="0123456789abcdef0123456789abcdef")
    uow = SqlModelUnitOfWork(session, InMemoryEventBus())

    # Mock uc with required dependencies
    use_case = ProcessAgentMessageUseCase(
        message_repository=None,  # Not used in preflight check
        memory_repository=None,
        project_access_policy=access_policy,
        context_builder=None,
        orchestrator=None,
        uow=uow,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
    )

    # 1. Non-owner gets rejected with owner_permission_required (0 tokens)
    res_editor = use_case._check_neon_integration_readiness(
        project_id=project.id,
        user_id=editor_id,
        prompt="despliega esto en neon",
    )
    assert res_editor is not None
    assert res_editor.metadata.get("outcome") == "owner_permission_required"
    assert "Solo el propietario" in res_editor.text

    # 2. Owner attempting direct mutation bypass gets pedagogical guidance (0 tokens)
    res_bypass = use_case._check_neon_integration_readiness(
        project_id=project.id,
        user_id=owner_id,
        prompt="elimina la tabla usuario en neon",
    )
    assert res_bypass is not None
    assert res_bypass.metadata.get("outcome") == "direct_mutation_bypass_prevented"
    assert "espejo automatizado" in res_bypass.text

    # 3. Owner with unconfigured API key gets unconfigured_api_key (0 tokens)
    res_unconf = use_case._check_neon_integration_readiness(
        project_id=project.id,
        user_id=owner_id,
        prompt="despliega esto en neon",
    )
    assert res_unconf is not None
    assert res_unconf.metadata.get("outcome") == "unconfigured_api_key"
    assert "primero debes ingresar tu API Key" in res_unconf.text

    # 4. Save API key but not initialized -> gets uninitialized_project (0 tokens)
    integration = ProjectIntegration.create(
        project_id=project.id,
        provider=IntegrationProvider.NEON,
        encrypted_api_key=crypto_service.encrypt("napi_valid_123"),
    )
    integration_repo.save(integration)
    uow.commit()

    res_uninit = use_case._check_neon_integration_readiness(
        project_id=project.id,
        user_id=owner_id,
        prompt="despliega esto en neon",
    )
    assert res_uninit is not None
    assert res_uninit.metadata.get("outcome") == "uninitialized_project"
    assert "aún no ha sido inicializada" in res_uninit.text

    # 5. When initialized -> preflight returns None (proceeds to orchestrator/tools)
    integration.mark_neon_initialized(
        neon_project_id="neon-proj-123",
        database_name="neondb",
        console_url="https://console.neon.tech/app/projects/test",
        branch_id="br-main",
        encrypted_connection_uri="postgresql://user:pass@ep-test.neon.tech/neondb",
    )
    integration_repo.save(integration)
    uow.commit()

    res_ok = use_case._check_neon_integration_readiness(
        project_id=project.id,
        user_id=owner_id,
        prompt="despliega esto en neon",
    )
    assert res_ok is None


@pytest.mark.anyio
async def test_neon_agent_tools_execution_and_response_formatting():
    # Fake sync use case
    class FakeSyncUseCase:
        def __init__(self, has_changes: bool = True):
            self.has_changes = has_changes

        def execute(self, cmd: SyncNeonDatabaseCommand) -> PostgresMigrationSummary:
            return PostgresMigrationSummary(
                created_tables=["pedidos"] if self.has_changes else [],
                dropped_tables=[],
                added_columns={"pedidos": ["monto"]} if self.has_changes else {},
                dropped_columns={},
                altered_columns={},
                added_foreign_keys=[] if self.has_changes else [],
                dropped_foreign_keys=[],
            )

    sync_uc = FakeSyncUseCase(has_changes=True)
    neon_tools = NeonAgentTools(
        project_id=uuid4(),
        user_id="owner-1",
        sync_neon_use_case=sync_uc,  # type: ignore
    )

    registry = ToolRegistry(
        actor_context=AgentToolActorContext(
            user_id="owner-1",
            project_id=neon_tools.project_id,
            message_id=uuid4(),
        )
    )
    neon_tools.register(registry)

    # Execute tool
    result = await registry.execute("sync_neon_database", {})
    assert result["status"] == "applied"
    assert result["has_changes"] is True
    assert "pedidos" in result["created_tables"]

    # Test CommunicableFact formatting in agent_response.py
    fact = CommunicableFact(
        result_type="confirmed_change",
        entity_type="neon_sync",
        entity_name="Base de datos Neon",
        action="updated",
        details="La base de datos en Neon fue sincronizada con éxito reflejando el diagrama UML actual.",
    )
    formatted = format_deterministic_response([fact], "mutation")
    assert "¡Listo!" in formatted
    assert "La base de datos en Neon fue sincronizada con éxito" in formatted
    assert "|" not in formatted  # Never output markdown tables


def test_direct_plan_neon_sync_has_mutation_kind():
    from app.modules.assistant.application.services.planning.action_planner import (
        ActionPlanner,
    )

    plan1 = ActionPlanner.build_direct_plan("sin croniza la base de datos en neon")
    assert plan1.tasks[0]["kind"] == "mutation"

    plan2 = ActionPlanner.build_direct_plan("Sí, sincroniza nuestro proyecto, a Neon.")
    assert plan2.tasks[0]["kind"] == "mutation"

    plan3 = ActionPlanner.build_direct_plan("sincroniza neon")
    assert plan3.tasks[0]["kind"] == "mutation"


@pytest.mark.anyio
async def test_plan_executor_allows_sync_neon_database_and_records_ledger():
    from app.modules.assistant.application.services.context_builder import AgentContext
    from app.modules.assistant.application.services.execution.plan_executor import (
        PlanExecutor,
    )
    from app.modules.assistant.application.services.planning.action_planner import (
        ActionPlanner,
    )
    from app.modules.assistant.application.ports.providers.ai_provider import (
        AiToolCall,
    )

    class FakeSyncUseCase:
        def execute(self, cmd):
            return PostgresMigrationSummary(
                created_tables=["cliente"],
                dropped_tables=[],
                added_columns={},
                dropped_columns={},
                altered_columns={},
                added_foreign_keys=[],
                dropped_foreign_keys=[],
            )

    class FakeAiProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, req):
            self.calls += 1
            if self.calls == 1:
                return AiResult(
                    text="",
                    tool_calls=[AiToolCall(id="call_1", name="sync_neon_database", arguments={})],
                    model_role=ModelRole.MAIN,
                    model="test-ai",
                )
            return AiResult(
                text="La base de datos fue sincronizada.",
                model_role=ModelRole.MAIN,
                model="test-ai",
            )

    proj_id = uuid4()
    neon_tools = NeonAgentTools(
        project_id=proj_id,
        user_id="owner-1",
        sync_neon_use_case=FakeSyncUseCase(),
    )
    registry = ToolRegistry(
        actor_context=AgentToolActorContext(
            user_id="owner-1",
            project_id=proj_id,
            message_id=uuid4(),
        )
    )
    neon_tools.register(registry)

    executor = PlanExecutor(
        ai_provider=FakeAiProvider(),
        tool_registry=registry,
    )
    context = AgentContext(
        project_id=proj_id,
        user_id="owner-1",
        instructions="",
        prompt="sin croniza la base de datos en neon",
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=100,
        compaction_threshold=1000,
        requires_compaction=False,
        authorized_mode="execute",
    )
    direct_plan = ActionPlanner.build_direct_plan("sin croniza la base de datos en neon")
    res = await executor.execute(context, direct_plan)

    assert "sincronizada" in res.text or "¡Listo!" in res.text or "Neon" in res.text
    assert direct_plan.status == "completed"
    assert any(entry.get("tool_name") == "sync_neon_database" for entry in direct_plan.operation_ledger)
