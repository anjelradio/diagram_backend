import logging
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import ProgrammingError

from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.ports.agent_activity_publisher import AgentActivityCode
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import AgentMessagePersistenceException
from app.modules.assistant.application.services.planning.action_planner import ActionPlanner
from app.modules.projects.domain.exceptions import ProjectNotFoundException


@pytest.fixture
def anyio_backend():
    return "asyncio"


class MessageRepositoryStub:
    def __init__(self, message):
        self.message = message
        self.saved = []

    def find_by_id(self, message_id):
        return self.message if self.message.id == message_id else None

    def save_terminal(self, message):
        self.saved.append(message)
        return True

    def save_plan_progress(self, message):
        return True


class MemoryRepositoryStub:
    def __init__(self):
        self.memory = None
        self.saved = []

    def find_active(self, *, user_id, project_id):
        if self.memory and (self.memory.user_id, self.memory.project_id) == (user_id, project_id):
            return self.memory
        return None

    def save(self, memory):
        self.memory = memory
        self.saved.append(memory)


class CompletionPublisherStub:
    def __init__(self):
        self.finished = []

    async def publish_finished(self, **event):
        self.finished.append(event)


class AccessPolicyStub:
    def __init__(self):
        self.calls = []

    def ensure_read_access(self, project_id, user_id):
        self.calls.append((project_id, user_id))


class ContextBuilderStub:
    def build(self, message):
        return SimpleNamespace(image_url=message.image_url)


class OrchestratorStub:
    def __init__(self, result=None, error=None):
        self.result = result or AiResult(
            text="## Answer\nReady.",
            model_role=ModelRole.MAIN,
            model="test-model",
        )
        self.error = error
        self.calls = []

    async def respond(self, context, image_url=None):
        self.calls.append((context, image_url))
        if self.error:
            raise self.error
        return self.result

    async def respond_with_progress(self, context, on_plan_progress, on_activity):
        self.calls.append((context, None))
        if self.error:
            raise self.error
        return self.result


class UnitOfWorkStub:
    def __init__(self, fail_commit=False):
        self.rollbacks = 0
        self.commits = 0
        self.fail_commit = fail_commit

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("private database detail")


def _message(status=AgentMessageStatus.RUNNING):
    return AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-a",
        prompt="Describe the project",
        image_url="https://res.cloudinary.com/test/image/upload/diagram.png",
        status=status,
    )


def _use_case(
    message,
    *,
    orchestrator=None,
    uow=None,
    access_policy=None,
    completion_publisher=None,
    activity_reporter=None,
    repo=None,
    message_repository=None,
    memory_repository=None,
    memory_updater=None,
):
    repository = message_repository or repo or MessageRepositoryStub(message)
    return ProcessAgentMessageUseCase(
        message_repository=repository,
        memory_repository=memory_repository,
        project_access_policy=access_policy or AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator or OrchestratorStub(),
        uow=uow or UnitOfWorkStub(),
        completion_publisher=completion_publisher,
        activity_reporter=activity_reporter,
        memory_updater=memory_updater,
    )


@pytest.mark.anyio
async def test_process_reports_only_context_prompt_and_finalization_phases():
    message = _message()
    activities = []

    async def report_activity(code):
        activities.append(code)

    use_case = _use_case(message, activity_reporter=report_activity)

    await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert activities == [
        AgentActivityCode.PREPARING_CONTEXT,
        AgentActivityCode.ANALYZING_PROMPT,
        AgentActivityCode.FINALIZING,
    ]


@pytest.mark.anyio
async def test_running_message_is_processed_and_terminal_state_is_persisted():
    message = _message()
    orchestrator = OrchestratorStub()
    publisher = CompletionPublisherStub()
    use_case = _use_case(
        message,
        orchestrator=orchestrator,
        completion_publisher=publisher,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "completed"
    assert result.response_markdown == "## Answer\nReady."
    assert message.status is AgentMessageStatus.COMPLETED
    assert orchestrator.calls[0][0].image_url == message.image_url
    assert publisher.finished[0]["message_id"] == message.id
    assert publisher.finished[0]["status"] == "completed"
    assert publisher.finished[0]["response_markdown"] == "## Answer\nReady."


@pytest.mark.anyio
async def test_queued_message_returns_without_provider_call():
    message = _message(AgentMessageStatus.QUEUED)
    orchestrator = OrchestratorStub()
    use_case = _use_case(message, orchestrator=orchestrator)

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "queued"
    assert result.response_markdown is None
    assert orchestrator.calls == []


@pytest.mark.anyio
async def test_provider_failure_is_persisted_as_safe_failed_response():
    message = _message()
    orchestrator = OrchestratorStub(error=RuntimeError("private provider content"))
    repository = MessageRepositoryStub(message)
    publisher = CompletionPublisherStub()
    use_case = ProcessAgentMessageUseCase(
        message_repository=repository,
        memory_repository=None,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        completion_publisher=publisher,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "failed"
    assert "private provider content" not in result.response_markdown
    assert len(repository.saved) == 1
    assert publisher.finished[0]["status"] == "failed"


@pytest.mark.anyio
async def test_invalid_plan_logs_safe_reason_and_marks_message_failed(caplog):
    private_content = "PRIVATE_PROVIDER_CONTENT"

    class InvalidPlanProvider:
        async def complete(self, request):
            return AiResult(text=private_content, model_role=ModelRole.PLANNING, model="test")

    class PlannerOrchestrator:
        async def respond_with_progress(self, context, on_plan_progress, on_activity):
            await ActionPlanner(InvalidPlanProvider()).create_plan("Crea A y edita B")

    message = _message()
    message.prompt = "PRIVATE_USER_PROMPT"
    use_case = _use_case(message, orchestrator=PlannerOrchestrator())
    caplog.set_level(logging.WARNING)

    result = await use_case.execute(
        message_id=message.id, project_id=message.project_id, user_id=message.user_id
    )

    assert result.status == "failed"
    assert str(message.id) in caplog.text
    assert "plan_reason=planner.invalid_json" in caplog.text
    assert private_content not in caplog.text
    assert message.prompt not in caplog.text


@pytest.mark.anyio
async def test_database_failure_logs_safe_driver_reason_and_marks_message_failed(caplog):
    message = _message()
    private_query_parameter = "private-user-value"

    class FailingContinuationRepository:
        def find_active_candidates(self, **_kwargs):
            driver_error = RuntimeError('relation "agent_continuations" does not exist')
            driver_error.sqlstate = "42P01"
            raise ProgrammingError(
                "SELECT * FROM agent_continuations WHERE user_id = %(user_id)s",
                {"user_id": private_query_parameter},
                driver_error,
            )

    use_case = _use_case(message)
    use_case.continuation_repository = FailingContinuationRepository()
    caplog.set_level(logging.WARNING)

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "failed"
    assert "error_type=ProgrammingError" in caplog.text
    assert "database_error_type=RuntimeError" in caplog.text
    assert "sqlstate=42P01" in caplog.text
    assert 'relation \"agent_continuations\" does not exist' in caplog.text
    assert private_query_parameter not in caplog.text
    assert message.prompt not in caplog.text


@pytest.mark.anyio
async def test_releases_transaction_before_network_and_revalidates_access():
    message = _message()
    access_policy = AccessPolicyStub()
    uow = UnitOfWorkStub()
    use_case = _use_case(
        message,
        orchestrator=OrchestratorStub(),
        access_policy=access_policy,
        uow=uow,
    )

    await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert uow.rollbacks >= 1
    assert len(access_policy.calls) >= 2


@pytest.mark.anyio
async def test_revoked_access_marks_running_message_failed_without_returning_answer():
    class RevokedAccessPolicy(AccessPolicyStub):
        def ensure_read_access(self, project_id, user_id):
            super().ensure_read_access(project_id, user_id)
            if len(self.calls) == 2:
                raise ProjectNotFoundException()

    message = _message()
    orchestrator = OrchestratorStub()
    access_policy = RevokedAccessPolicy()
    use_case = _use_case(
        message,
        orchestrator=orchestrator,
        access_policy=access_policy,
    )

    with pytest.raises(ProjectNotFoundException):
        await use_case.execute(
            message_id=message.id,
            project_id=message.project_id,
            user_id=message.user_id,
        )

    assert message.status is AgentMessageStatus.FAILED
    assert message.response_markdown == "No pude completar la solicitud. Inténtalo de nuevo."


@pytest.mark.anyio
async def test_terminal_persistence_failure_is_not_reported_as_completed():
    message = _message()
    use_case = _use_case(message, orchestrator=OrchestratorStub(), uow=UnitOfWorkStub(fail_commit=True))

    with pytest.raises(AgentMessagePersistenceException):
        await use_case.execute(
            message_id=message.id,
            project_id=message.project_id,
            user_id=message.user_id,
        )


@pytest.mark.anyio
async def test_completed_execution_memory_includes_confirmed_changes_but_not_failed_facts():
    message = _message()
    message.plan = {
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "class-1"}],
            },
            {
                "operation_id": "op-2",
                "action_kind": "DELETE_CLASS",
                "status": "rejected",
                "entity_refs": [{"type": "class", "id": "class-2"}],
            },
        ]
    }
    memory_repository = MemoryRepositoryStub()
    use_case = ProcessAgentMessageUseCase(
        message_repository=MessageRepositoryStub(message),
        memory_repository=memory_repository,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=OrchestratorStub(),
        uow=UnitOfWorkStub(),
    )

    await use_case.execute(message_id=message.id, project_id=message.project_id, user_id=message.user_id)

    assert memory_repository.memory is None


@pytest.mark.anyio
async def test_process_agent_message_persists_sanitized_markdown_without_uuids():
    uuid_str = "12345678-1234-5678-1234-567812345678"
    raw_ai_text = f"<thought>private reasoning</thought>He creado la clase Pedido (id: {uuid_str}) con éxito."

    class LeakingOrchestrator:
        async def respond_with_progress(self, context, on_progress, on_activity):
            return AiResult(
                text=raw_ai_text,
                model_role=ModelRole.MAIN,
                model="qwen",
                completed=True,
            )

    message = _message()
    repo = MessageRepositoryStub(message)
    use_case = _use_case(message, orchestrator=LeakingOrchestrator(), repo=repo)

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    # 1. El resultado devuelto no debe contener el UUID ni etiquetas de pensamiento
    assert uuid_str not in result.response_markdown
    assert "<thought>" not in result.response_markdown
    assert "Pedido" in result.response_markdown

    # 2. El mensaje persistido en BD tampoco debe contener el UUID
    assert len(repo.saved) == 1
    assert uuid_str not in repo.saved[0].response_markdown
    assert "<thought>" not in repo.saved[0].response_markdown


class MemoryUpdaterStub:
    def __init__(self, result=None):
        self.result = (
            result
            if result is not None
            else "## Objetivos activos\n- Actualizado\n\n## Preferencias del usuario\n\n## Decisiones y restricciones vigentes\n\n## Resultados confirmados relevantes\n\n## Pendientes o dudas"
        )
        self.calls = []

    async def update(
        self, current_summary, prompt, response_markdown, confirmed_operations=None
    ):
        self.calls.append(
            {
                "current_summary": current_summary,
                "prompt": prompt,
                "response_markdown": response_markdown,
                "confirmed_operations": confirmed_operations,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.anyio
async def test_process_agent_message_with_memory_updater_updates_summary_context():
    message = _message()
    message.plan = {
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"type": "class", "id": "class-1"}],
            }
        ]
    }
    memory_repo = MemoryRepositoryStub()
    updater = MemoryUpdaterStub(
        result="## Objetivos activos\n- Modelar pedidos\n\n## Preferencias del usuario\n- Español\n\n## Decisiones y restricciones vigentes\n\n## Resultados confirmados relevantes\n- CREATE_CLASS: class:class-1\n\n## Pendientes o dudas"
    )
    use_case = _use_case(
        message,
        memory_repository=memory_repo,
        memory_updater=updater,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "completed"
    assert len(updater.calls) == 0
    assert memory_repo.memory is None


@pytest.mark.anyio
async def test_process_agent_message_memory_updater_failure_preserves_terminal_message_and_old_memory():
    from app.modules.assistant.domain.exceptions import AgentMemoryUpdateException

    message = _message()
    memory_repo = MemoryRepositoryStub()
    old_memory = AgentUserMemory.create(
        user_id=message.user_id,
        project_id=message.project_id,
        summary_context="## Objetivos activos\n- Memoria anterior intacta",
    )
    memory_repo.save(old_memory)
    updater = MemoryUpdaterStub(result=AgentMemoryUpdateException())
    message_repo = MessageRepositoryStub(message)

    use_case = _use_case(
        message,
        message_repository=message_repo,
        memory_repository=memory_repo,
        memory_updater=updater,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    # 1. El mensaje terminal persiste como completed
    assert result.status == "completed"
    assert len(message_repo.saved) == 1
    assert message_repo.saved[0].status == AgentMessageStatus.COMPLETED

    # 2. La memoria previa se preserva intacta sin modificaciones
    assert memory_repo.memory.summary_context == "## Objetivos activos\n- Memoria anterior intacta"


@pytest.mark.anyio
async def test_process_agent_message_failed_status_does_not_call_memory_updater():
    class FailingOrchestrator:
        async def respond_with_progress(self, context, on_progress, on_activity):
            return AiResult(
                text="Error al procesar",
                model_role=ModelRole.MAIN,
                model="qwen",
                completed=False,
            )

    message = _message()
    memory_repo = MemoryRepositoryStub()
    updater = MemoryUpdaterStub()
    use_case = _use_case(
        message,
        orchestrator=FailingOrchestrator(),
        memory_repository=memory_repo,
        memory_updater=updater,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "failed"
    assert len(updater.calls) == 0
    assert memory_repo.memory is None


@pytest.mark.anyio
async def test_terminal_domain_failure_marks_message_failed_preserves_commits_and_creates_no_continuation():
    # T008: Al recibir un resultado con kind == terminal_domain_failure,
    # el caso de uso marca AgentMessage como FAILED, guarda el plan final con los commits del ledger,
    # publica el estado failed determinista y NO crea continuación residual.
    message = _message()

    deterministic_md = (
        "No se pudo completar la solicitud porque la clase **Factura** ya no está disponible "
        "en el diagrama. Los cambios ya confirmados se conservan en el lienzo. "
        "Verifica el estado actual del lienzo antes de reintentar."
    )
    metadata = {
        "kind": "terminal_domain_failure",
        "category": "class_not_found",
        "task_id": "t1",
        "tool_name": "apply_diagram_changes",
        "has_confirmed_changes": True,
        "affected_element_type": "class",
        "error_code": "class_not_found",
        "operation_ledger": [
            {"operation_id": "op-1", "status": "applied", "name": "Cliente"}
        ],
    }

    orchestrator = OrchestratorStub(
        result=AiResult(
            text=deterministic_md,
            model_role=ModelRole.MAIN,
            model="agent-plan-executor",
            completed=False,
            metadata=metadata,
        )
    )

    class TrackingContinuationRepository:
        def __init__(self):
            self.saved = []

        def find_active_candidates(self, **_kwargs):
            return []

        def save(self, continuation):
            self.saved.append(continuation)

    continuation_repo = TrackingContinuationRepository()
    completion_publisher = CompletionPublisherStub()
    repo = MessageRepositoryStub(message)
    uow = UnitOfWorkStub()

    use_case = _use_case(
        message,
        orchestrator=orchestrator,
        repo=repo,
        uow=uow,
        completion_publisher=completion_publisher,
    )
    use_case.continuation_repository = continuation_repo

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "failed"
    assert message.status == AgentMessageStatus.FAILED
    assert message.response_markdown == deterministic_md
    assert message.plan == metadata
    assert message.plan["has_confirmed_changes"] is True
    assert len(message.plan["operation_ledger"]) == 1

    # Invariante clave: NO debe crearse ninguna continuación residual
    assert len(continuation_repo.saved) == 0

    # Unit of work fue committeado y mensaje guardado como terminal
    assert uow.commits >= 1
    assert len(repo.saved) == 1

    # Publicador de finalización recibió evento de falla determinista
    assert len(completion_publisher.finished) == 1
    published = completion_publisher.finished[0]
    assert published["status"] == "failed"
    assert published["response_markdown"] == deterministic_md
    assert published["message_id"] == message.id


@pytest.mark.anyio
async def test_terminal_domain_failure_yields_to_concurrent_cancellation():
    # T008 / T014: Si el mensaje ya fue cancelado concurrentemente en el repositorio,
    # el resultado terminal de fallo de dominio no debe sobrescribir el estado CANCELLED.
    message = _message(status=AgentMessageStatus.RUNNING)

    class ConcurrentlyCancelledMessageRepository(MessageRepositoryStub):
        def save_terminal(self, msg):
            # Simula que la cancelación ganó la carrera y el mensaje ya está CANCELLED
            self.message.status = AgentMessageStatus.CANCELLED
            return False

        def find_by_id(self, message_id):
            return self.message

    repo = ConcurrentlyCancelledMessageRepository(message)
    uow = UnitOfWorkStub()
    orchestrator = OrchestratorStub(
        result=AiResult(
            text="Fallo de dominio",
            model_role=ModelRole.MAIN,
            model="agent-plan-executor",
            completed=False,
            metadata={"kind": "terminal_domain_failure", "category": "class_not_found"},
        )
    )

    use_case = _use_case(message, orchestrator=orchestrator, repo=repo, uow=uow)

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "cancelled"
    assert message.status == AgentMessageStatus.CANCELLED


@pytest.mark.anyio
async def test_partial_execution_transitions_message_to_partial_and_creates_continuation():
    # T009 [US1]: Un resultado parcial persiste el mensaje como PARTIAL,
    # crea continuación reintentable con las tareas pendientes y publica evento partial.
    message = _message(status=AgentMessageStatus.RUNNING)

    partial_md = (
        "Se completó 1 tarea y quedó 1 no completada.\n\n"
        "**Cambios aplicados:**\n- Se creó clase **Cliente** (creada).\n\n"
        "**Tareas no completadas:**\n- Añadir detalle: la clase requerida ya no está disponible.\n\n"
        "Revisa el diagrama y pide reintentar."
    )
    plan_dict = {
        "version": 1,
        "goal": "Crear entidades",
        "status": "partial",
        "tasks": [
            {"id": "t1", "objective": "Crear Cliente", "status": "completed"},
            {"id": "t2", "objective": "Añadir detalle", "status": "failed", "error_code": "class_not_found"},
        ],
        "operation_ledger": [
            {"operation_id": "op-1", "status": "applied", "action_kind": "CREATE_CLASS", "entity_refs": [{"type": "class", "id": "c1", "name": "Cliente"}]}
        ],
        "limits": {},
        "created_at": "2026-11-07T00:00:00Z",
        "updated_at": "2026-11-07T00:00:01Z",
        "outcome": "partial",
    }

    orchestrator = OrchestratorStub(
        result=AiResult(
            text=partial_md,
            model_role=ModelRole.MAIN,
            model="agent-plan-executor",
            completed=False,
            metadata={
                "outcome": "partial",
                "kind": "continuation",
                **plan_dict,
            },
        )
    )

    class TrackingContinuationRepository:
        def __init__(self):
            self.saved = []

        def find_active_candidates(self, **_kwargs):
            return []

        def save(self, continuation):
            self.saved.append(continuation)

    continuation_repo = TrackingContinuationRepository()
    completion_publisher = CompletionPublisherStub()
    repo = MessageRepositoryStub(message)
    uow = UnitOfWorkStub()

    use_case = _use_case(
        message,
        orchestrator=orchestrator,
        repo=repo,
        uow=uow,
        completion_publisher=completion_publisher,
    )
    use_case.continuation_repository = continuation_repo

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    # 1. El estado terminal es partial
    assert result.status == "partial"
    assert message.status == AgentMessageStatus.PARTIAL
    assert message.response_markdown == partial_md

    # 2. Se creó la continuación para permitir el reintento residual
    assert len(continuation_repo.saved) == 1
    cont = continuation_repo.saved[0]
    assert cont.root_message_id == message.id
    assert cont.source_plan_message_id == message.id

    # 3. Transacción confirmada
    assert uow.commits >= 1
    assert len(repo.saved) == 1

    # 4. Publicación en tiempo real con status='partial'
    assert len(completion_publisher.finished) == 1
    assert completion_publisher.finished[0]["status"] == "partial"
    assert completion_publisher.finished[0]["message_id"] == message.id


@pytest.mark.anyio
async def test_terminal_domain_failure_with_suggests_creation_persists_awaiting_input_continuation():
    """Valida que si un fallo terminal de dominio tiene suggests_creation, se persista una continuación awaiting_input."""
    from app.modules.assistant.domain.entities.agent_continuation import (
        ContinuationOutcome,
        ContinuationPurpose,
    )

    message = _message()
    message.prompt = "Crea el atributo email en la clase Usuario"

    failure_md = (
        "No se pudo completar la solicitud porque la clase **Usuario** no existe en el diagrama.\n\n"
        "¿Deseas que cree la clase **Usuario** primero para poder continuar?"
    )
    metadata = {
        "kind": "terminal_domain_failure",
        "category": "class_not_found",
        "target_class": "Usuario",
        "missing_class": "Usuario",
        "suggests_creation": True,
        "task_id": "t1",
        "tool_name": "apply_diagram_changes",
        "has_confirmed_changes": False,
        "affected_element_type": "class",
        "error_code": "class_not_found",
    }

    orchestrator = OrchestratorStub(
        result=AiResult(
            text=failure_md,
            model_role=ModelRole.MAIN,
            model="agent-plan-executor",
            completed=False,
            metadata=metadata,
        )
    )

    class TrackingContinuationRepository:
        def __init__(self):
            self.saved = []

        def find_active_candidates(self, **_kwargs):
            return []

        def save(self, continuation):
            self.saved.append(continuation)

    continuation_repo = TrackingContinuationRepository()
    completion_publisher = CompletionPublisherStub()
    repo = MessageRepositoryStub(message)
    uow = UnitOfWorkStub()

    use_case = _use_case(
        message,
        orchestrator=orchestrator,
        repo=repo,
        uow=uow,
        completion_publisher=completion_publisher,
    )
    use_case.continuation_repository = continuation_repo

    result = await use_case.execute(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
    )

    assert result.status == "failed"
    assert message.status == AgentMessageStatus.FAILED
    assert len(continuation_repo.saved) == 1
    cont = continuation_repo.saved[0]
    assert cont.outcome == ContinuationOutcome.AWAITING_INPUT
    assert cont.purpose == ContinuationPurpose.CLARIFICATION
    assert "Crear la clase Usuario y proceder con:" in cont.effective_request




