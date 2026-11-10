import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlmodel import Session

from app.modules.assistant.application.ports.agent_author_name_reader import (
    AgentAuthorNameReader,
)
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.services.context_builder import (
    AgentContext,
    ContextBuilder,
)
from app.modules.assistant.application.services.continuation.residual_plan_builder import (
    ResidualPlanBuilder,
)
from app.modules.assistant.application.services.execution.plan_executor import (
    PlanExecutor,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    AgentToolActorContext,
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.services.integrations.notion_agent_tools import (
    NotionAgentTools,
)
from app.modules.assistant.application.services.intent import (
    SemanticCategory,
    SemanticIntentRouter,
    SemanticTurnDecision,
)
from app.modules.assistant.application.services.planning.action_planner import (
    ActionPlanner,
)
from app.modules.assistant.application.services.planning.agent_orchestrator import (
    AgentOrchestrator,
)
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
    _is_multiple_notion_tasks_request,
    _is_single_notion_task_execution_request,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationOutcome,
    ContinuationPurpose,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.domain.enums.agent_message_status import (
    AgentMessageStatus,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionInitializedWorkspace,
    NotionIntegrationProvider,
    NotionProjectWelcomeContent,
    NotionTaskRecord,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.enums.notion_task_priority import (
    NotionTaskPriority,
)
from app.modules.integrations.domain.enums.notion_task_status import (
    NotionTaskStatus,
)
from app.modules.integrations.domain.exceptions import (
    NotionTaskOwnershipException,
)
from app.modules.integrations.infrastructure.persistence.models.project_integration_model import (
    ProjectIntegrationModel,
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


class MemoryNotionProvider(NotionIntegrationProvider):
    def __init__(self) -> None:
        self.tasks: dict[str, NotionTaskRecord] = {}

    def validate_api_key(self, api_key: str, *, parent_page_id: str | None = None):
        return True, "parent-uuid", "Workspace"

    def initialize_project_workspace(
        self,
        *,
        api_key: str,
        parent_page_id: str,
        project_name: str,
        welcome_content: NotionProjectWelcomeContent,
    ) -> NotionInitializedWorkspace:
        return NotionInitializedWorkspace(
            page_id="p-1",
            database_id="db-1",
            page_url="https://notion.so/p-1",
        )

    def create_task(
        self,
        *,
        api_key: str,
        database_id: str,
        title: str,
        description: str,
        assignee_name: str,
        priority: NotionTaskPriority,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        task_id = f"task-{len(self.tasks) + 1}"
        record = NotionTaskRecord(
            task_id=task_id,
            title=title,
            description=description,
            status=NotionTaskStatus.PENDING,
            priority=priority,
            assignee_name=assignee_name,
            due_date=due_date,
            url=f"https://notion.so/{task_id}",
        )
        self.tasks[task_id] = record
        return record

    def list_tasks(
        self,
        *,
        api_key: str,
        database_id: str,
        assignee_name: str | None = None,
        status: NotionTaskStatus | None = None,
    ) -> list[NotionTaskRecord]:
        res = list(self.tasks.values())
        if assignee_name:
            res = [t for t in res if t.assignee_name == assignee_name]
        if status:
            res = [t for t in res if t.status == status]
        return res

    def get_task(self, *, api_key: str, task_id: str) -> NotionTaskRecord | None:
        return self.tasks.get(task_id)

    def update_task(
        self,
        *,
        api_key: str,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: NotionTaskStatus | None = None,
        priority: NotionTaskPriority | None = None,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        curr = self.tasks[task_id]
        updated = NotionTaskRecord(
            task_id=curr.task_id,
            title=title if title is not None else curr.title,
            description=description if description is not None else curr.description,
            status=status if status is not None else curr.status,
            priority=priority if priority is not None else curr.priority,
            assignee_name=curr.assignee_name,
            due_date=due_date if due_date is not None else curr.due_date,
            url=curr.url,
        )
        self.tasks[task_id] = updated
        return updated

    def delete_task(self, *, api_key: str, task_id: str) -> bool:
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False


class StubAuthorReader(AgentAuthorNameReader):
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    def find_names(self, user_ids: set[str]) -> dict[str, str]:
        return {uid: self.names.get(uid, "Colaborador") for uid in user_ids}


class StubAiProvider(AiProvider):
    def __init__(self, responses: list[AiResult] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.calls.append(request)
        if self.responses:
            return self.responses.pop(0)
        return AiResult(text="OK", model_role=ModelRole.MAIN, model="stub")


@pytest.mark.anyio
async def test_notion_agent_tools_crud_and_user_isolation(session: Session):
    owner_id = "user-juan"
    collab_id = "user-maria"

    u_juan = BetterAuthUser(id=owner_id, name="Juan Perez", email="juan@example.com")
    u_maria = BetterAuthUser(id=collab_id, name="Maria Gomez", email="maria@example.com")
    session.add_all([u_juan, u_maria])

    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    crypto = IntegrationCryptoService(secret="test-secret-1234567890")
    provider = MemoryNotionProvider()
    integration_repo = SQLModelProjectIntegrationRepository(session)

    # Configurar e inicializar integración
    integration = ProjectIntegrationModel(
        project_id=proj.id,
        provider=IntegrationProvider.NOTION.value,
        encrypted_api_key=crypto.encrypt("ntn_valid_key"),
        is_initialized=True,
        external_database_id="db-123",
        external_page_id="page-123",
    )
    session.add(integration)
    session.commit()

    # 1. Crear tarea con Juan
    registry_juan = ToolRegistry(
        max_arguments_chars=4000,
        actor_context=AgentToolActorContext(project_id=proj.id, user_id=owner_id, message_id=uuid4()),
    )
    tools_juan = NotionAgentTools(
        project_id=proj.id,
        current_user_name="Juan Perez",
        integration_repository=integration_repo,
        crypto_service=crypto,
        notion_provider=provider,
    )
    tools_juan.register(registry_juan)

    create_res = await registry_juan.execute(
        "create_notion_task",
        {"title": "Agregar stock_minimo a Producto", "priority": "Alta"},
    )
    assert create_res["status"] == "applied"
    assert create_res["task"]["assignee"] == "Juan Perez"
    assert create_res["task"]["status"] == "Pendiente"
    task_id = create_res["task"]["task_id"]

    # 2. Listar tareas con Juan -> Debe ver 1 tarea
    list_juan = await registry_juan.execute("list_notion_tasks", {})
    assert list_juan["tasks_count"] == 1
    assert list_juan["tasks"][0]["task_id"] == task_id
    assert list_juan["tasks"][0]["title"] == "Agregar stock_minimo a Producto"

    # 3. Listar tareas con Maria -> Debe ver 0 tareas (Aislamiento por usuario)
    registry_maria = ToolRegistry(
        max_arguments_chars=4000,
        actor_context=AgentToolActorContext(project_id=proj.id, user_id=collab_id, message_id=uuid4()),
    )
    tools_maria = NotionAgentTools(
        project_id=proj.id,
        current_user_name="Maria Gomez",
        integration_repository=integration_repo,
        crypto_service=crypto,
        notion_provider=provider,
    )
    tools_maria.register(registry_maria)

    list_maria = await registry_maria.execute("list_notion_tasks", {})
    assert list_maria["tasks_count"] == 0

    # 4. Maria intenta modificar la tarea de Juan -> Debe lanzar NotionTaskOwnershipException
    with pytest.raises(NotionTaskOwnershipException):
        await registry_maria.execute(
            "update_notion_task",
            {"task_id": task_id, "status": "Done"},
        )

    # 5. Maria intenta eliminar la tarea de Juan -> Debe lanzar NotionTaskOwnershipException
    with pytest.raises(NotionTaskOwnershipException):
        await registry_maria.execute(
            "delete_notion_task",
            {"task_id": task_id},
        )

    # 6. Juan actualiza su propia tarea a Done -> Éxito
    update_res = await registry_juan.execute(
        "update_notion_task",
        {"task_id": task_id, "status": "Done"},
    )
    assert update_res["status"] == "applied"
    assert update_res["task"]["status"] == "Done"

    # 7. Juan elimina su propia tarea -> Éxito
    delete_res = await registry_juan.execute(
        "delete_notion_task",
        {"task_id": task_id},
    )
    assert delete_res["status"] == "applied"
    assert delete_res["deleted"] is True


def test_rejection_of_multiple_notion_tasks_regex():
    assert _is_multiple_notion_tasks_request("Haz todas las tareas de Notion") is True
    assert _is_multiple_notion_tasks_request("ejecuta todas mis tareas pendientes") is True
    assert _is_multiple_notion_tasks_request("haz las tareas 1 y 2 de notion") is True
    assert _is_multiple_notion_tasks_request("aplica varias tareas de notion") is True
    assert _is_multiple_notion_tasks_request("ejecuta la tarea 1 de notion") is False
    assert _is_multiple_notion_tasks_request("crea una clase Producto") is False


def test_action_planner_attaches_done_closure_task():
    plan = ExecutionPlan.create(
        goal="Crear clase Producto",
        tasks=[
            {
                "id": "task-create-product",
                "objective": "Crear la clase Producto con id y nombre",
                "kind": "mutation",
                "depends_on": [],
            }
        ],
    )

    plan_with_closure = ActionPlanner.attach_notion_task_closure(
        plan,
        notion_task_id="task-100",
        notion_task_title="Agregar clase Producto",
    )

    assert len(plan_with_closure.tasks) == 2
    closure_task = plan_with_closure.tasks[1]
    assert closure_task["id"] == "close-notion-task-100"
    assert closure_task["kind"] == "mutation"
    assert closure_task["depends_on"] == ["task-create-product"]
    assert closure_task["notion_task_id"] == "task-100"


def test_residual_plan_preserves_notion_closure_as_last_task():
    plan = ExecutionPlan.create(
        goal="Plan con Notion",
        tasks=[
            {
                "id": "t1",
                "objective": "Crear clase Producto",
                "kind": "mutation",
                "depends_on": [],
            },
            {
                "id": "close-notion-123",
                "objective": "Marcar tarea como Done",
                "kind": "mutation",
                "depends_on": ["t1"],
                "notion_task_id": "123",
            },
        ],
    )
    # Simular que t1 quedó incompleta
    builder = ResidualPlanBuilder()
    residual = builder.build(plan)
    assert residual is not None
    assert len(residual.tasks) == 2
    assert residual.tasks[0]["id"] == "t1"
    assert residual.tasks[1]["id"] == "close-notion-123"
    assert residual.tasks[1]["depends_on"] == ["t1"]


@pytest.mark.anyio
async def test_plan_executor_executes_done_closure_when_mutations_succeed(session: Session):
    owner_id = "user-juan"
    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    provider = MemoryNotionProvider()
    crypto = IntegrationCryptoService(secret="test-secret-1234567890")
    integration_repo = SQLModelProjectIntegrationRepository(session)
    integration = ProjectIntegrationModel(
        project_id=proj.id,
        provider=IntegrationProvider.NOTION.value,
        encrypted_api_key=crypto.encrypt("ntn_valid_key"),
        is_initialized=True,
        external_database_id="db-123",
        external_page_id="page-123",
    )
    session.add(integration)
    session.commit()

    # Tarea inicial en Notion
    task = provider.create_task(
        api_key="ntn_valid_key",
        database_id="db-123",
        title="Crear clase Producto",
        description="Crear clase Producto",
        assignee_name="Juan Perez",
        priority=NotionTaskPriority.HIGH,
    )
    assert task.status == NotionTaskStatus.PENDING

    registry = ToolRegistry(
        max_arguments_chars=4000,
        actor_context=AgentToolActorContext(project_id=proj.id, user_id=owner_id, message_id=uuid4()),
    )
    tools = NotionAgentTools(
        project_id=proj.id,
        current_user_name="Juan Perez",
        integration_repository=integration_repo,
        crypto_service=crypto,
        notion_provider=provider,
    )
    tools.register(registry)

    # Registrar herramienta mock de mutación de diagrama
    mock_apply = AsyncMock(return_value={"status": "applied", "confirmed": True})
    registry.register(
        RegisteredTool(
            definition=AiToolDefinition(name="apply_diagram_changes", description="Mock diagram", parameters={}),
            handler=mock_apply,
            mutating=True,
        )
    )

    ai_provider = StubAiProvider(
        responses=[
            AiResult(
                text="Clase creada",
                model_role=ModelRole.MAIN,
                model="test",
                tool_calls=(
                    AiToolCall(id="c1", name="apply_diagram_changes", arguments={"actions": []}),
                ),
            )
        ]
    )

    executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=registry,
        max_tool_calls=10,
        max_execution_seconds=10,
    )

    plan = ExecutionPlan.create(
        goal="Ejecutar tarea de Notion",
        tasks=[
            {
                "id": "mut-1",
                "objective": "Crear clase Producto",
                "kind": "mutation",
                "depends_on": [],
            },
            {
                "id": f"close-notion-{task.task_id}",
                "objective": "Marcar tarea como Done",
                "kind": "mutation",
                "depends_on": ["mut-1"],
                "notion_task_id": task.task_id,
            },
        ],
    )

    context = AgentContext(
        user_id=owner_id,
        project_id=proj.id,
        instructions="",
        prompt="Ejecuta la tarea",
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=100,
        compaction_threshold=1000,
        requires_compaction=False,
    )

    result = await executor.execute(context, plan)
    assert result.completed is True
    # Verificar que el proveedor de Notion ahora tiene la tarea en Done
    updated_task = provider.get_task(api_key="ntn_valid_key", task_id=task.task_id)
    assert updated_task.status == NotionTaskStatus.DONE


@pytest.mark.anyio
async def test_process_agent_message_rejects_multiple_notion_tasks(session: Session):
    owner_id = "user-juan"
    u_juan = BetterAuthUser(id=owner_id, name="Juan Perez", email="juan@example.com")
    session.add(u_juan)
    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    msg_repo = SQLModelAgentMessageRepository(session, worker_id="")
    author_reader = StubAuthorReader({owner_id: "Juan Perez"})

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=access_policy,
        context_builder=MagicMock(),
        orchestrator=MagicMock(),
        uow=uow,
        author_profile_reader=author_reader,
    )

    msg = AgentMessage(
        id=uuid4(),
        project_id=proj.id,
        user_id=owner_id,
        prompt="Haz todas las tareas de Notion",
        status=AgentMessageStatus.RUNNING,
    )
    msg_repo.save_new(msg)

    result = await use_case.execute(message_id=msg.id, project_id=proj.id, user_id=owner_id)
    assert result.status == "completed"
    assert "Solo puedo ejecutar una tarea de Notion a la vez" in result.response_markdown


@pytest.mark.anyio
async def test_process_agent_message_rejects_mixed_diagram_and_notion_requests(session: Session):
    owner_id = "user-juan"
    u_juan = BetterAuthUser(id=owner_id, name="Juan Perez", email="juan@example.com")
    session.add(u_juan)
    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    msg_repo = SQLModelAgentMessageRepository(session, worker_id="")
    author_reader = StubAuthorReader({owner_id: "Juan Perez"})

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=access_policy,
        context_builder=MagicMock(),
        orchestrator=MagicMock(),
        uow=uow,
        author_profile_reader=author_reader,
    )

    # 1. Petición directa mixta: Mutación de clase + Notion
    msg_mixed = AgentMessage(
        id=uuid4(),
        project_id=proj.id,
        user_id=owner_id,
        prompt="Crea la clase Factura y además crea una tarea en Notion",
        status=AgentMessageStatus.RUNNING,
    )
    msg_repo.save_new(msg_mixed)

    result = await use_case.execute(message_id=msg_mixed.id, project_id=proj.id, user_id=owner_id)
    assert result.status == "completed"
    assert "He detectado que solicitas tanto modificaciones en el diagrama como acciones en Notion" in result.response_markdown
    assert "¿Deseas que primero aplique los cambios en el lienzo o que primero gestione la tarea en Notion?" in result.response_markdown

    # 2. Petición pura de Notion basada en sugerencia previa: NO debe ser rechazada como mixta
    from app.modules.assistant.application.use_cases.process_agent_message import _is_mixed_diagram_and_notion_request
    assert _is_mixed_diagram_and_notion_request("Agrega esa sugerencia a una tarea nueva de Notion") is False
    assert _is_mixed_diagram_and_notion_request("Crea una tarea en Notion para revisar Factura") is False
    assert _is_mixed_diagram_and_notion_request("Dime qué tareas tengo en Notion") is False
    assert _is_mixed_diagram_and_notion_request("ejecuta la tarea 1 de notion") is False


@pytest.mark.anyio
async def test_execute_single_notion_task_with_missing_context_initiates_continuation_and_completes_to_done(session: Session):
    owner_id = "user-juan"
    u_juan = BetterAuthUser(id=owner_id, name="Juan Perez", email="juan@example.com")
    session.add(u_juan)
    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    msg_repo = SQLModelAgentMessageRepository(session, worker_id="")
    author_reader = StubAuthorReader({owner_id: "Juan Perez"})
    cont_repo = SQLModelAgentContinuationRepository(session)

    provider = MemoryNotionProvider()
    crypto = IntegrationCryptoService(secret="test-secret-1234567890")
    integration_repo = SQLModelProjectIntegrationRepository(session)

    integration = ProjectIntegrationModel(
        project_id=proj.id,
        provider=IntegrationProvider.NOTION.value,
        encrypted_api_key=crypto.encrypt("ntn_valid_key"),
        is_initialized=True,
        external_database_id="db-123",
        external_page_id="page-123",
    )
    session.add(integration)
    session.commit()

    # Tarea en Notion con datos faltantes (falta target class)
    task = provider.create_task(
        api_key="ntn_valid_key",
        database_id="db-123",
        title="Relaciona la clase Producto",
        description="",
        assignee_name="Juan Perez",
        priority=NotionTaskPriority.HIGH,
    )

    router = SemanticIntentRouter(ai_provider=None)  # Usará fallback

    registry = ToolRegistry(
        max_arguments_chars=4000,
        actor_context=AgentToolActorContext(project_id=proj.id, user_id=owner_id, message_id=uuid4()),
    )
    tools = NotionAgentTools(
        project_id=proj.id,
        current_user_name="Juan Perez",
        integration_repository=integration_repo,
        crypto_service=crypto,
        notion_provider=provider,
    )
    tools.register(registry)

    # Mock de apply_diagram_changes
    mock_apply = AsyncMock(return_value={"status": "applied", "confirmed": True})
    registry.register(
        RegisteredTool(
            definition=AiToolDefinition(name="apply_diagram_changes", description="Mock diagram", parameters={}),
            handler=mock_apply,
            mutating=True,
        )
    )

    ai_provider = StubAiProvider(
        responses=[
            AiResult(
                text="Relación creada",
                model_role=ModelRole.MAIN,
                model="test",
                tool_calls=(
                    AiToolCall(id="c1", name="apply_diagram_changes", arguments={"actions": []}),
                ),
            )
        ]
    )

    executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=registry,
        max_tool_calls=10,
        max_execution_seconds=10,
    )
    planner = ActionPlanner(ai_provider=ai_provider)
    orchestrator = AgentOrchestrator(
        ai_provider=ai_provider,
        action_planner=planner,
        plan_executor=executor,
    )

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=access_policy,
        context_builder=ContextBuilder(),
        orchestrator=orchestrator,
        uow=uow,
        author_profile_reader=author_reader,
        continuation_repository=cont_repo,
        semantic_intent_router=router,
        integration_repository=integration_repo,
        notion_provider=provider,
        crypto_service=crypto,
    )

    # --- Turno 1: Usuario pide ejecutar la tarea 1 ---
    msg_1 = AgentMessage(
        id=uuid4(),
        project_id=proj.id,
        user_id=owner_id,
        prompt="Ejecuta la tarea 1 de Notion",
        status=AgentMessageStatus.RUNNING,
    )
    msg_repo.save_new(msg_1)

    res_1 = await use_case.execute(message_id=msg_1.id, project_id=proj.id, user_id=owner_id)
    assert res_1.status == "completed"
    assert "¿Con qué otra clase del diagrama deseas relacionar la clase Producto?" in res_1.response_markdown

    # Verificar que se creó la continuación activa recordando active_notion_task
    candidates = cont_repo.find_active_candidates(project_id=proj.id, user_id=owner_id, limit=1)
    assert len(candidates) == 1
    assert candidates[0].dialog_state is not None
    assert candidates[0].dialog_state["active_notion_task"]["task_id"] == task.task_id

    # --- Turno 2: Usuario responde con la clase faltante ---
    msg_2 = AgentMessage(
        id=uuid4(),
        project_id=proj.id,
        user_id=owner_id,
        prompt="con Categoría",
        status=AgentMessageStatus.RUNNING,
    )
    msg_repo.save_new(msg_2)

    res_2 = await use_case.execute(message_id=msg_2.id, project_id=proj.id, user_id=owner_id)
    assert res_2.status == "completed"

    # Verificar que la tarea de Notion fue marcada como Done al completar el plan
    updated = provider.get_task(api_key="ntn_valid_key", task_id=task.task_id)
    assert updated.status == NotionTaskStatus.DONE


@pytest.mark.anyio
async def test_process_agent_message_creates_notion_task_from_suggestion(
    session: Session,
):
    """Verifica que el usuario pueda pedir 'Agrega esa sugerencia a una tarea de notion'
    y que la tarea sea creada exitosamente vía create_notion_task sin ser bloqueada como tarea de solo lectura."""
    owner_id = "user-juan"
    u_juan = BetterAuthUser(id=owner_id, name="Juan Perez", email="juan@example.com")
    session.add(u_juan)
    proj = ProjectModel(name="Diagram Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    msg_repo = SQLModelAgentMessageRepository(session, worker_id="")
    author_reader = StubAuthorReader({owner_id: "Juan Perez"})
    cont_repo = SQLModelAgentContinuationRepository(session)

    provider = MemoryNotionProvider()
    crypto = IntegrationCryptoService(secret="test-secret-1234567890")
    integration_repo = SQLModelProjectIntegrationRepository(session)

    integration = ProjectIntegrationModel(
        project_id=proj.id,
        provider=IntegrationProvider.NOTION.value,
        encrypted_api_key=crypto.encrypt("ntn_valid_key"),
        is_initialized=True,
        external_database_id="db-123",
        external_page_id="page-123",
    )
    session.add(integration)
    session.commit()

    # Simular proveedor de IA que resuelve el tool call de create_notion_task
    ai_provider = MagicMock(spec=AiProvider)
    call_count = 0

    async def mock_complete(req: AiRequest) -> AiResult:
        nonlocal call_count
        call_count += 1
        if req.purpose == "task_execution" and call_count == 1:
            return AiResult(
                text="",
                model_role=req.model_role,
                model="deepseek",
                tool_calls=(
                    AiToolCall(
                        id="call_create_task_1",
                        name="create_notion_task",
                        arguments={
                            "title": "Agregar atributos a la clase Usuario",
                            "description": "nombre, email, rol, activo",
                        },
                    ),
                ),
            )
        return AiResult(
            text="He creado la tarea en Notion exitosamente.",
            model_role=req.model_role,
            model="main",
        )

    ai_provider.complete.side_effect = mock_complete

    notion_tools = NotionAgentTools(
        notion_provider=provider,
        integration_repository=integration_repo,
        crypto_service=crypto,
        project_id=proj.id,
        current_user_name="Juan Perez",
    )
    registry = ToolRegistry(actor_context=AgentToolActorContext(user_id=owner_id, project_id=proj.id, message_id=uuid4()))
    notion_tools.register(registry)

    plan_executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=registry,
        max_tool_calls=10,
        max_execution_seconds=10,
    )
    planner = ActionPlanner(ai_provider=ai_provider)
    orchestrator = AgentOrchestrator(
        ai_provider=ai_provider,
        action_planner=planner,
        plan_executor=plan_executor,
    )

    router = AsyncMock(spec=SemanticIntentRouter)
    decision = SemanticTurnDecision(
        category=SemanticCategory.CONTINUATION_OR_ANAPHORA,
        reasoning="Usuario pide crear tarea en Notion a partir de sugerencia previa.",
        resolved_goal="Crear una nueva tarea en Notion asignada al usuario con título 'Agregar atributos a la clase Usuario' y descripción detallada usando create_notion_task.",
        requires_mutation=True,
        raw_message="Agrega esa sugerencia a una una tarea de notion",
    )
    router.route.return_value = decision
    router.route_turn.return_value = decision

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=access_policy,
        context_builder=ContextBuilder(),
        orchestrator=orchestrator,
        uow=uow,
        author_profile_reader=author_reader,
        continuation_repository=cont_repo,
        semantic_intent_router=router,
        integration_repository=integration_repo,
        notion_provider=provider,
        crypto_service=crypto,
    )

    msg = AgentMessage(
        id=uuid4(),
        project_id=proj.id,
        user_id=owner_id,
        prompt="Agrega esa sugerencia a una una tarea de notion",
        status=AgentMessageStatus.RUNNING,
    )
    msg_repo.save_new(msg)

    res = await use_case.execute(message_id=msg.id, project_id=proj.id, user_id=owner_id)
    assert res.status == "completed"
    assert len(provider.tasks) == 1
    created_task = list(provider.tasks.values())[0]
    assert created_task.title == "Agregar atributos a la clase Usuario"

