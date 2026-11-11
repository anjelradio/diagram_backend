from datetime import datetime, timezone
import json
from uuid import UUID, uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiRequest,
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.services.audit.audit_query_service import (
    AuditQueryService,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.diagram.diagram_audit_tools import (
    DiagramAuditTools,
)
from app.modules.assistant.application.services.execution.plan_executor import (
    PlanExecutor,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    AgentToolActorContext,
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.application.services.planning.action_planner import (
    ActionPlanner,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.collaboration.application.ports.readers.project_member_list_reader import (
    ProjectMemberItem,
    ProjectMemberListReader,
)
from app.modules.collaboration.domain.enums.project_member_role import (
    ProjectMemberRole,
)
from app.modules.collaboration.domain.enums.project_member_status import (
    ProjectMemberStatus,
)
from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.repositories.diagram_audit_log_repository import (
    DiagramAuditLogRepository,
)


def _make_context(prompt: str, project_id: UUID, user_id: str) -> AgentContext:
    return AgentContext(
        project_id=project_id,
        user_id=user_id,
        instructions="instructions",
        prompt=prompt,
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=100,
        requires_compaction=False,
        authorized_mode="read_only",
    )


class InMemoryAuditRepo(DiagramAuditLogRepository):
    def __init__(self, logs=None):
        self.logs = logs or []

    def save(self, audit_log: DiagramAuditLog) -> None:
        self.logs.append(audit_log)

    def find_by_id(self, audit_log_id: UUID) -> DiagramAuditLog | None:
        return next((l for l in self.logs if l.id == audit_log_id), None)

    def list_by_project(
        self,
        project_id: UUID,
        *,
        user_id: str | None = None,
        user_search: str | None = None,
        actor_type=None,
        entity_type=None,
        entity_id=None,
        entity_name: str | None = None,
        parent_class_id=None,
        parent_class_name: str | None = None,
        action=None,
        since=None,
        until=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiagramAuditLog]:
        res = [l for l in self.logs if l.project_id == project_id]
        if user_id:
            res = [l for l in res if l.user_id == user_id]
        if user_search:
            res = [l for l in res if user_search.lower() in l.user_name.lower()]
        if entity_name:
            res = [l for l in res if entity_name.lower() in l.entity_name.lower()]
        if parent_class_name:
            res = [
                l
                for l in res
                if l.parent_class_name
                and parent_class_name.lower() in l.parent_class_name.lower()
            ]
        if action:
            res = [l for l in res if l.action == action]
        if entity_type:
            res = [l for l in res if l.entity_type == entity_type]
        if since:
            res = [l for l in res if l.created_date >= since]
        if until:
            res = [l for l in res if l.created_date <= until]
        return res[:limit]


class InMemoryMemberReader(ProjectMemberListReader):
    def __init__(self, members):
        self.members = members

    def list_members(self, project_id, status=None):
        return self.members


class ScriptedAuditAiProvider(AiProvider):
    """Proveedor AI simulado para verificar llamadas a herramientas y síntesis."""

    def __init__(self, script: list[AiResult]):
        self.script = list(script)
        self.recorded_requests: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.recorded_requests.append(request)
        if not self.script:
            return AiResult(
                text="Fin de simulación.",
                model_role=request.model_role,
                model="mock-scripted",
                completed=True,
            )
        return self.script.pop(0)


@pytest.mark.anyio
async def test_diagram_audit_tools_argument_validation():
    """Valida rechazo estricto de parámetros no reconocidos en query_diagram_audit_logs."""
    proj_id = uuid4()
    audit_service = AuditQueryService(audit_repository=InMemoryAuditRepo())
    tools = DiagramAuditTools(audit_service, project_id=proj_id, user_id="usr-1")

    # Clave no permitida
    with pytest.raises(AgentToolArgumentsException):
        await tools._query_audit_logs({"invalid_key": "val"})

    # Action inválida
    with pytest.raises(AgentToolArgumentsException):
        await tools._query_audit_logs({"action": "NOT_AN_ACTION"})

    # Entity type inválido
    with pytest.raises(AgentToolArgumentsException):
        await tools._query_audit_logs({"entity_type": "INVALID_TYPE"})

    # Time filter inválido
    with pytest.raises(AgentToolArgumentsException):
        await tools._query_audit_logs({"time_filter": "next_year"})


@pytest.mark.anyio
async def test_agent_flow_query_who_created_class():
    """Flujo E2E: '¿Quién creó la clase Producto?'."""
    proj_id = uuid4()
    class_id = uuid4()
    created_dt = datetime(2026, 11, 5, 14, 32, 0, tzinfo=timezone.utc)

    log_entry = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-carlos",
        user_name="Carlos Mendoza",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Producto",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Creó la clase Producto",
        payload_after={"id": str(class_id), "name": "Producto"},
        created_date=created_dt,
    )

    audit_repo = InMemoryAuditRepo([log_entry])
    audit_service = AuditQueryService(audit_repository=audit_repo)

    registry = ToolRegistry(
        actor_context=AgentToolActorContext(
            project_id=proj_id,
            user_id="usr-test",
            message_id=uuid4(),
        )
    )
    DiagramAuditTools(audit_service, project_id=proj_id, user_id="usr-test").register(
        registry
    )

    # El modelo primero invoca query_diagram_audit_logs, y tras recibir la respuesta sintetiza
    ai_provider = ScriptedAuditAiProvider(
        [
            # Turno 1: LLM propone tool call
            AiResult(
                text="",
                tool_calls=(
                    AiToolCall(
                        id="call-1",
                        name="query_diagram_audit_logs",
                        arguments={
                            "entity_name": "Producto",
                            "entity_type": "CLASS",
                            "action": "CREATE",
                        },
                    ),
                ),
                model_role=ModelRole.EXECUTION,
                model="qwen-mock",
                completed=True,
            ),
            # Turno 2: LLM sintetiza la respuesta con los datos recibidos
            AiResult(
                text=(
                    "La clase **Producto** fue creada por **Carlos Mendoza** "
                    "el 5 de noviembre de 2026 a las 14:32 UTC."
                ),
                model_role=ModelRole.MAIN,
                model="qwen-mock",
                completed=True,
            ),
        ]
    )

    prompt = "¿Quién creó la clase Producto?"
    plan = ActionPlanner.build_direct_plan(prompt)
    assert plan.tasks[0]["kind"] == "answer"

    executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=registry,
    )
    context = _make_context(prompt, proj_id, "usr-test")

    result = await executor.execute(context, plan)

    # 1. El resultado contiene la respuesta final sintetizada
    assert "Carlos Mendoza" in result.text
    assert "Producto" in result.text

    # 2. Inmunidad mutativa: No se ejecutó ninguna mutación en el diagrama
    assert len(plan.operation_ledger) == 0


@pytest.mark.anyio
async def test_agent_flow_query_what_collaborator_did_today():
    """Flujo E2E: '¿Qué hizo Juan hoy?'."""
    proj_id = uuid4()
    class_id = uuid4()
    attr_id = uuid4()
    now_utc = datetime(2026, 11, 10, 16, 0, 0, tzinfo=timezone.utc)

    log1 = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-juan",
        user_name="Juan Pérez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Pedido",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Creó la clase Pedido",
        payload_after={"id": str(class_id), "name": "Pedido"},
        created_date=datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc),
    )
    log2 = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-juan",
        user_name="Juan Pérez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.ATTRIBUTE,
        entity_id=attr_id,
        entity_name="monto",
        parent_class_id=class_id,
        parent_class_name="Pedido",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_ATTRIBUTE",
        summary="Agregó el atributo monto a Pedido",
        payload_after={"id": str(attr_id), "name": "monto", "type": "float"},
        created_date=datetime(2026, 11, 10, 10, 15, 0, tzinfo=timezone.utc),
    )

    members = [
        ProjectMemberItem(
            id=uuid4(),
            user_id="usr-juan",
            name="Juan Pérez",
            email="juan@test.com",
            image=None,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        )
    ]
    audit_repo = InMemoryAuditRepo([log1, log2])
    audit_service = AuditQueryService(
        audit_repository=audit_repo,
        member_reader=InMemoryMemberReader(members),
    )

    registry = ToolRegistry(
        actor_context=AgentToolActorContext(
            project_id=proj_id,
            user_id="usr-test",
            message_id=uuid4(),
        )
    )
    DiagramAuditTools(audit_service, project_id=proj_id, user_id="usr-test").register(
        registry
    )

    ai_provider = ScriptedAuditAiProvider(
        [
            AiResult(
                text="",
                tool_calls=(
                    AiToolCall(
                        id="call-juan",
                        name="query_diagram_audit_logs",
                        arguments={
                            "collaborator_name": "Juan",
                            "time_filter": "today",
                        },
                    ),
                ),
                model_role=ModelRole.EXECUTION,
                model="qwen-mock",
                completed=True,
            ),
            AiResult(
                text=(
                    "Hoy (10 de noviembre de 2026), **Juan Pérez** realizó las siguientes acciones en el diagrama:\n"
                    "- **Clase Pedido**:\n"
                    "  - Creó la clase.\n"
                    "  - Agregó el atributo `monto` (tipo `float`)."
                ),
                model_role=ModelRole.MAIN,
                model="qwen-mock",
                completed=True,
            ),
        ]
    )

    prompt = "¿Qué hizo Juan hoy?"
    plan = ActionPlanner.build_direct_plan(prompt)
    assert plan.tasks[0]["kind"] == "answer"

    executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=registry,
    )
    context = _make_context(prompt, proj_id, "usr-test")

    result = await executor.execute(context, plan)
    assert "Juan Pérez" in result.text
    assert "Pedido" in result.text
    assert "monto" in result.text
    assert len(plan.operation_ledger) == 0


@pytest.mark.anyio
async def test_diagram_audit_tools_local_timezone_and_custom_override():
    """Valida que query_diagram_audit_logs retorne horas locales de Bolivia y admita override de zona horaria."""
    proj_id = uuid4()
    class_id = uuid4()

    # Evento creado a las 08:27:47 UTC (04:27:47 en Bolivia, UTC-4)
    event_dt = datetime(2026, 11, 11, 8, 27, 47, tzinfo=timezone.utc)
    log_entry = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-1",
        user_name="Luciana",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Casa",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Se creó la clase Casa",
        payload_after={"id": str(class_id), "name": "Casa"},
        created_date=event_dt,
    )

    audit_repo = InMemoryAuditRepo([log_entry])
    audit_service = AuditQueryService(audit_repository=audit_repo)
    tools = DiagramAuditTools(audit_service, project_id=proj_id, user_id="usr-1")

    # 1. Consulta predeterminada (America/La_Paz)
    res_bolivia = await tools._query_audit_logs({"entity_name": "Casa"})
    assert res_bolivia["status"] == "success"
    assert res_bolivia["timezone"] == "America/La_Paz"
    assert res_bolivia["timezone_label"] == "hora de Bolivia"
    sample = res_bolivia["events_sample"][0]
    assert sample["local_time"] == "04:27:47"
    assert sample["local_time_display"] == "04:27:47, hora de Bolivia"
    assert sample["formatted_event"] == "Se creó la clase Casa (04:27:47, hora de Bolivia)"

    # 2. Consulta con override de zona horaria (UTC)
    res_utc = await tools._query_audit_logs({"entity_name": "Casa", "timezone": "UTC"})
    assert res_utc["status"] == "success"
    assert res_utc["timezone"] == "UTC"
    assert res_utc["timezone_label"] == "hora UTC"
    sample_utc = res_utc["events_sample"][0]
    assert sample_utc["local_time"] == "08:27:47"
    assert sample_utc["local_time_display"] == "08:27:47, hora UTC"
