"""Pruebas de integración para la continuidad de mensajes del agente en ProcessAgentMessageUseCase."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolution,
    ContinuationResolver,
    ResolutionDecision,
)
from app.modules.assistant.application.services.continuation.request_readiness import (
    RequestReadiness,
)
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
)
from app.modules.assistant.application.services.dialog.context_assembler import (
    ContextAssembler,
)
from app.modules.assistant.application.services.dialog.dialog_manager import (
    DialogManager,
)
from app.modules.assistant.application.services.dialog.dialog_policy import (
    DialogPolicy,
)
from app.modules.assistant.application.services.dialog.turn_interpreter import (
    TurnInterpreter,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.repositories.agent_continuation_repository import (
    AgentContinuationRepository,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class InMemoryContinuationRepository(AgentContinuationRepository):
    def __init__(self):
        self.continuations: dict[UUID, AgentContinuation] = {}

    def save(self, continuation: AgentContinuation) -> None:
        self.continuations[continuation.id] = continuation

    def find_by_id(self, continuation_id: UUID) -> AgentContinuation | None:
        return self.continuations.get(continuation_id)

    def find_by_root_message_id(self, root_message_id: UUID) -> AgentContinuation | None:
        for c in self.continuations.values():
            if c.root_message_id == root_message_id:
                return c
        return None

    def find_active_by_scope(
        self,
        *,
        project_id: UUID,
        user_id: str,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        current_time = now or datetime.now(timezone.utc)
        for c in sorted(self.continuations.values(), key=lambda item: item.updated_date, reverse=True):
            if (
                c.project_id == project_id
                and c.user_id == user_id
                and c.purpose == ContinuationPurpose.CLARIFICATION
                and c.state in (ContinuationState.AWAITING_INPUT, ContinuationState.READY, ContinuationState.CLAIMED)
                and c.expires_at > current_time
            ):
                return c
        return None

    def list_active_candidates(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = 3,
        purpose: ContinuationPurpose | str | None = None,
        now: datetime | None = None,
    ) -> list[AgentContinuation]:
        current_time = now or datetime.now(timezone.utc)
        purpose_val = (
            purpose.value
            if isinstance(purpose, ContinuationPurpose)
            else str(purpose)
            if purpose is not None
            else None
        )
        result = [
            c
            for c in self.continuations.values()
            if c.project_id == project_id
            and c.user_id == user_id
            and c.state in (ContinuationState.AWAITING_INPUT, ContinuationState.READY)
            and c.expires_at > current_time
            and (purpose_val is None or c.purpose.value == purpose_val)
        ]
        return result[:limit]

    def claim_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        by_message_id: UUID | None = None,
        new_message_id: UUID | None = None,
        user_id: str | None = None,
        project_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        c = self.continuations.get(continuation_id)
        if not c:
            return None
        target_msg = by_message_id or new_message_id
        if (
            c.version == expected_version
            and c.state in (ContinuationState.AWAITING_INPUT, ContinuationState.READY)
        ):
            claimed = c.claim(by_message_id=target_msg, expected_version=expected_version)
            self.continuations[continuation_id] = claimed
            return claimed
        return None

    def resolve_atomic(
        self,
        *,
        continuation_id: UUID,
        expected_version: int,
        outcome: ContinuationOutcome = ContinuationOutcome.SUCCESS,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.RESOLVED,
        now: datetime | None = None,
    ) -> AgentContinuation | None:
        c = self.continuations.get(continuation_id)
        if not c or c.version != expected_version:
            return None
        resolved = c.resolve(outcome=outcome, close_reason=close_reason)
        self.continuations[continuation_id] = resolved
        return resolved

    def close_claimed_by_message(
        self,
        *,
        message_id: UUID,
        close_reason: ContinuationCloseReason | str = ContinuationCloseReason.CANCELLED,
        now: datetime | None = None,
    ) -> int:
        count = 0
        for cid, c in list(self.continuations.items()):
            if c.claimed_by_message_id == message_id and c.state == ContinuationState.CLAIMED:
                self.continuations[cid] = c.close(close_reason)
                count += 1
        return count


class MessageRepositoryStub:
    def __init__(self):
        self.messages: dict[UUID, AgentMessage] = {}
        self.saved_terminal: list[AgentMessage] = []

    def add(self, message: AgentMessage) -> None:
        self.messages[message.id] = message

    def find_by_id(self, message_id: UUID) -> AgentMessage | None:
        return self.messages.get(message_id)

    def save_terminal(self, message: AgentMessage) -> bool:
        self.messages[message.id] = message
        self.saved_terminal.append(message)
        return True

    def save_plan_progress(self, message: AgentMessage) -> bool:
        self.messages[message.id] = message
        return True


class AccessPolicyStub:
    def ensure_read_access(self, project_id: UUID, user_id: str) -> None:
        pass


class ContextBuilderStub:
    def build(self, message: AgentMessage) -> Any:
        return SimpleNamespace(
            image_url=message.image_url,
            user_prompt=message.prompt,
            conversation_context="",
        )


class OrchestratorStub:
    def __init__(
        self,
        response_text: str = "Relación creada exitosamente.",
        metadata: dict | None = None,
    ):
        self.response_text = response_text
        self.metadata = metadata
        self.calls: list[Any] = []

    async def respond_with_progress(self, context, on_plan_progress, on_activity):
        self.calls.append(context)
        return AiResult(
            text=self.response_text,
            model_role=ModelRole.MAIN,
            model="test-model",
            metadata=self.metadata,
        )


class UnitOfWorkStub:
    def rollback(self):
        pass

    def commit(self):
        pass


@pytest.mark.anyio
async def test_explicit_topic_switch_executes_only_the_new_request(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", True)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    message = AgentMessage(
        id=uuid4(), project_id=uuid4(), user_id="user-123",
        prompt="Olvida lo anterior, crea una clase Producto",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(message)
    orchestrator = OrchestratorStub()
    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        dialog_manager=DialogManager(continuation_repository=continuation_repo),
    )

    result = await use_case.execute(message_id=message.id)

    assert result.status == "completed"
    assert orchestrator.calls[0].prompt == "crea una clase Producto"
    assert message_repo.find_by_id(message.id).prompt == message.prompt


@pytest.mark.anyio
async def test_process_agent_message_creates_continuation_on_missing_critical_data():
    project_id = uuid4()
    user_id = "user-123"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Relaciona Producto con Categoría",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg1)

    orchestrator = OrchestratorStub()
    readiness = RequestReadiness()
    resolver = ContinuationResolver(ai_provider=None)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=resolver,
        request_readiness=readiness,
    )

    result = await use_case.execute(message_id=msg1.id)

    # 1. El turno finaliza como completed para el usuario
    assert result.status == "completed"

    # 2. Se creó un AgentContinuation con estado awaiting_input
    active_candidates = continuation_repo.find_active_candidates(
        project_id=project_id, user_id=user_id
    )
    assert len(active_candidates) == 1
    continuation = active_candidates[0]
    assert continuation.state == ContinuationState.AWAITING_INPUT
    assert continuation.root_message_id == msg1.id
    assert continuation.effective_request == "Relaciona Producto con Categoría"
    assert len(continuation.missing_fields) > 0

    # 3. El prompt del mensaje original permanece intacto
    persisted_msg1 = message_repo.find_by_id(msg1.id)
    assert persisted_msg1.prompt == "Relaciona Producto con Categoría"
    # La respuesta formuló una pregunta
    assert "¿" in persisted_msg1.response_markdown or "tipo" in persisted_msg1.response_markdown


@pytest.mark.anyio
async def test_two_step_clarification_chain_completes_request():
    project_id = uuid4()
    user_id = "user-123"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    orchestrator = OrchestratorStub(response_text="Asociación entre Producto y Categoría creada.")
    readiness = RequestReadiness()
    resolver = ContinuationResolver(ai_provider=None)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=resolver,
        request_readiness=readiness,
    )

    # Turno 1: Solicitud inicial
    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Relaciona Producto con Categoría",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg1)
    await use_case.execute(message_id=msg1.id)

    # Turno 2: Usuario aclara el tipo ("asociación")
    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="asociación",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg2)
    res2 = await use_case.execute(message_id=msg2.id)
    assert res2.status == "completed"

    active_cand = continuation_repo.find_active_candidates(project_id=project_id, user_id=user_id)
    assert len(active_cand) == 1
    # Continúa awaiting_input porque aún faltan cardinalidades
    assert active_cand[0].state == ContinuationState.AWAITING_INPUT
    assert active_cand[0].version == 2

    # Turno 3: Usuario aclara cardinalidades ("1 en Categoria y 0..* en Producto")
    msg3 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="1 en Categoria y 0..* en Producto",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg3)
    res3 = await use_case.execute(message_id=msg3.id)
    assert res3.status == "completed"

    # Ahora debe quedar resuelto
    final_cont = continuation_repo.find_by_id(active_cand[0].id)
    assert final_cont.state == ContinuationState.RESOLVED
    assert final_cont.outcome == ContinuationOutcome.SUCCESS
    # El orquestador fue invocado
    assert len(orchestrator.calls) == 1


@pytest.mark.anyio
async def test_partial_execution_and_continue_flow():
    """Recorrido parcial -> 'sí, continúa' -> success."""
    project_id = uuid4()
    user_id = "user-partial-1"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    # Plan previo donde la clase Pedido fue aplicada y la asociación quedó pendiente
    t1_id = str(uuid4())
    t2_id = str(uuid4())
    prior_plan_dict = {
        "version": 1,
        "goal": "Crear Pedido y asociarlo a Cliente",
        "status": "failed",
        "tasks": [
            {
                "id": t1_id,
                "objective": "Crear clase Pedido",
                "kind": "mutation",
                "status": "completed",
                "depends_on": [],
                "operation_ids": ["op-1"],
                "result_refs": [{"id": "ped-1", "type": "class", "name": "Pedido"}],
            },
            {
                "id": t2_id,
                "objective": "Crear relación Pedido con Cliente",
                "kind": "mutation",
                "status": "failed",
                "depends_on": [t1_id],
                "operation_ids": ["op-2"],
                "result_refs": [],
            },
        ],
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "task_id": t1_id,
                "tool_name": "diagram_class_tools",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"id": "ped-1", "type": "class", "name": "Pedido"}],
            }
        ],
        "limits": {},
        "created_at": "2026-11-05T00:00:00Z",
        "updated_at": "2026-11-05T00:00:00Z",
    }

    # Turno 1: el orquestador devuelve resultado parcial
    partial_orchestrator = OrchestratorStub(
        response_text="Creé la clase Pedido pero no pude asociarla a Cliente. ¿Deseas continuar?",
        metadata={
            "kind": "continuation",
            "outcome": "partial",
            "prior_execution_plan": prior_plan_dict,
        },
    )

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=partial_orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=ContinuationResolver(ai_provider=None),
        request_readiness=RequestReadiness(),
    )

    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crear Pedido y asociarlo a Cliente",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg1)
    res1 = await use_case.execute(message_id=msg1.id)
    assert res1.status == "partial"

    # Se creó una continuación con outcome partial y state ready
    cands = continuation_repo.find_active_candidates(project_id=project_id, user_id=user_id)
    assert len(cands) == 1
    assert cands[0].outcome == ContinuationOutcome.PARTIAL
    assert cands[0].source_plan_message_id == msg1.id

    # Turno 2: Usuario confirma 'sí, continúa'
    continuation_orchestrator = OrchestratorStub(response_text="Relación creada con éxito.")
    use_case.orchestrator = continuation_orchestrator

    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="sí, continúa",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg2)
    res2 = await use_case.execute(message_id=msg2.id)
    assert res2.status == "completed"

    # La continuación debe haber quedado resuelta como success
    resolved_cand = continuation_repo.find_by_id(cands[0].id)
    assert resolved_cand.state == ContinuationState.RESOLVED
    assert resolved_cand.outcome == ContinuationOutcome.SUCCESS


@pytest.mark.anyio
async def test_continue_yes_when_critical_fields_still_missing():
    """Si el usuario dice 'sí' pero aún faltan campos críticos, no se debe mutar ni resolver; se repregunta."""
    project_id = uuid4()
    user_id = "user-missing-yes"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    orchestrator = OrchestratorStub(response_text="Debería no ser llamado.")
    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=ContinuationResolver(ai_provider=None),
        request_readiness=RequestReadiness(),
    )

    # Turno 1: solicitud con datos faltantes
    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Relaciona Producto con Categoría",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg1)
    await use_case.execute(message_id=msg1.id)

    # Turno 2: el usuario solo dice "sí"
    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="sí",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg2)
    res2 = await use_case.execute(message_id=msg2.id)

    assert res2.status == "completed"
    # No se llamó al orquestador para mutar
    assert len(orchestrator.calls) == 0

    # La continuación sigue en awaiting_input
    active_cand = continuation_repo.find_active_candidates(project_id=project_id, user_id=user_id)
    assert len(active_cand) == 1
    assert active_cand[0].state == ContinuationState.AWAITING_INPUT
    # La respuesta repregunta por los datos faltantes
    persisted_msg2 = message_repo.find_by_id(msg2.id)
    assert "¿" in persisted_msg2.response_markdown or "tipo" in persisted_msg2.response_markdown



@pytest.mark.anyio
@pytest.mark.parametrize("has_old_pending", [False, True])
async def test_accepts_recent_recommendation_without_resuming_an_old_pending_request(has_old_pending):
    import json
    from unittest.mock import AsyncMock, Mock

    from app.modules.assistant.application.ports.readers.agent_conversation_reader import RecentExchange
    from app.modules.assistant.application.services.context_builder import AgentContext

    project_id = uuid4()
    user_id = "user-venta"
    pending = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relaciona Caballo con Caballito",
        missing_fields=[{"key": "relation.type", "critical": True, "question": "¿Qué tipo?"}],
    )
    continuations = InMemoryContinuationRepository()
    if has_old_pending:
        continuations.save(pending)
    messages = MessageRepositoryStub()
    message = AgentMessage(
        id=uuid4(), project_id=project_id, user_id=user_id,
        prompt="Sí, agrega todos", status=AgentMessageStatus.RUNNING,
    )
    messages.add(message)
    reader = Mock()
    reader.get_recent_exchanges.return_value = [
        RecentExchange(
            message_id=uuid4(), created_at=datetime.now(timezone.utc),
            user_prompt="¿Qué atributos recomiendas para Venta?",
            assistant_response="Sugiero total, estado, metodo_pago y descuento.",
        )
    ]
    effective_request = "Agrega a Venta los atributos total, estado, metodo_pago y descuento."
    provider = AsyncMock()
    provider.complete.return_value = AiResult(
        text=json.dumps({"decision": "recent_follow_up", "effective_request": effective_request}),
        model_role=ModelRole.MAIN,
        model="test-model",
    )
    context_builder = Mock()
    context_builder.build.return_value = AgentContext(
        user_id=user_id, project_id=project_id, instructions="", prompt=message.prompt,
        summary_context="", image_url=None, memory_id=None, estimated_memory_tokens=0,
        compaction_threshold=1000, requires_compaction=False,
    )
    orchestrator = OrchestratorStub()
    use_case = ProcessAgentMessageUseCase(
        message_repository=messages, memory_repository=None,
        continuation_repository=continuations, project_access_policy=AccessPolicyStub(),
        context_builder=context_builder, orchestrator=orchestrator, uow=UnitOfWorkStub(),
        continuation_resolver=ContinuationResolver(ai_provider=provider),
        conversation_reader=reader,
    )

    result = await use_case.execute(message_id=message.id)

    assert result.status == "completed"
    assert [context.prompt for context in orchestrator.calls] == [effective_request]
    if has_old_pending:
        assert continuations.find_by_id(pending.id).state == ContinuationState.AWAITING_INPUT
    reader.get_recent_exchanges.assert_called_once_with(
        project_id=project_id, user_id=user_id, exclude_message_id=message.id, limit=3,
    )
    provider.complete.assert_awaited_once()
    payload = json.loads(provider.complete.await_args.args[0].messages[1].content)
    assert payload["recent_conversation_turns"][-1]["assistant"].startswith("Sugiero total")


@pytest.mark.anyio
async def test_recommends_relation_using_pending_classes_without_claiming_mutation():
    import json
    from unittest.mock import AsyncMock, Mock

    from app.modules.assistant.application.ports.readers.agent_conversation_reader import RecentExchange
    from app.modules.assistant.application.services.context_builder import AgentContext
    from app.modules.assistant.application.services.planning.agent_intent import requires_mutation

    project_id = uuid4()
    user_id = "user-relations"
    messages = MessageRepositoryStub()
    continuations = InMemoryContinuationRepository()
    reader = Mock()
    provider = AsyncMock()
    context_builder = Mock()
    orchestrator = OrchestratorStub(response_text="Si cada producto tiene una categoría, sugiero 1:N.")
    use_case = ProcessAgentMessageUseCase(
        message_repository=messages, memory_repository=None,
        continuation_repository=continuations, project_access_policy=AccessPolicyStub(),
        context_builder=context_builder, orchestrator=orchestrator, uow=UnitOfWorkStub(),
        continuation_resolver=ContinuationResolver(ai_provider=provider),
        conversation_reader=reader,
    )
    original = AgentMessage(
        id=uuid4(), project_id=project_id, user_id=user_id, status=AgentMessageStatus.RUNNING,
        prompt="quiero que haga una relación entre la clase categoría y la clase producto",
    )
    messages.add(original)

    await use_case.execute(message_id=original.id)

    pending = continuations.find_by_root_message_id(original.id)
    assert pending is not None
    assert [field["key"] for field in pending.missing_fields] == ["relation.type"]
    assert not orchestrator.calls
    provider.complete.assert_not_awaited()
    reader.get_recent_exchanges.assert_not_called()

    follow_up = AgentMessage(
        id=uuid4(), project_id=project_id, user_id=user_id, status=AgentMessageStatus.RUNNING,
        prompt="¿Cuál es la relación que tú me recomiendas?",
    )
    messages.add(follow_up)
    reader.get_recent_exchanges.return_value = [
        RecentExchange(
            message_id=original.id, created_at=datetime.now(timezone.utc),
            user_prompt=original.prompt, assistant_response=original.response_markdown,
        )
    ]
    effective_request = "¿Qué tipo de relación recomiendas entre Categoría y Producto?"
    provider.complete.return_value = AiResult(
        text=json.dumps({"decision": "recent_follow_up", "effective_request": effective_request}),
        model_role=ModelRole.MAIN, model="test-model",
    )
    context_builder.build.return_value = AgentContext(
        user_id=user_id, project_id=project_id, instructions="", prompt=follow_up.prompt,
        summary_context="", image_url=None, memory_id=None, estimated_memory_tokens=0,
        compaction_threshold=1000, requires_compaction=False,
    )

    result = await use_case.execute(message_id=follow_up.id)

    assert result.status == "completed"
    assert [context.prompt for context in orchestrator.calls] == [effective_request]
    assert not requires_mutation(orchestrator.calls[0].prompt)
    assert continuations.find_by_id(pending.id).state == ContinuationState.AWAITING_INPUT
    payload = json.loads(provider.complete.await_args.args[0].messages[1].content)
    assert payload["recent_conversation_turns"][-1]["user"] == original.prompt


@pytest.mark.anyio
async def test_continuation_topic_change_closes_pending_thread_and_executes_new_request():
    """Un cambio de tema no reanuda el hilo anterior y procesa la nueva solicitud de manera independiente."""
    import json
    from unittest.mock import AsyncMock

    project_id = uuid4()
    user_id = "user-topic-change"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    # Hilo previo esperando aclaración
    pending = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relaciona Libro con Autor",
        missing_fields=[{"key": "relation.type", "critical": True, "question": "¿Qué tipo?"}],
    )
    continuation_repo.save(pending)

    new_msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crea la clase Factura con total: float",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(new_msg)

    # Provider resuelve NEW_REQUEST (cambio de tema)
    provider = AsyncMock()
    provider.complete.return_value = AiResult(
        text=json.dumps({"decision": "new_request", "effective_request": "Crea la clase Factura con total: float"}),
        model_role=ModelRole.MAIN,
        model="test-model",
    )
    resolver = ContinuationResolver(ai_provider=provider)
    orchestrator = OrchestratorStub(response_text="Clase Factura creada exitosamente.")

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=resolver,
        request_readiness=RequestReadiness(),
    )

    result = await use_case.execute(message_id=new_msg.id)
    assert result.status == "completed"
    assert len(orchestrator.calls) == 1
    assert "Factura" in orchestrator.calls[0].user_prompt


@pytest.mark.anyio
async def test_continuation_explicit_decline_cancels_pending_thread():
    """Un rechazo explícito cancela el hilo pendiente sin invocar mutaciones en el orquestador."""
    import json
    from unittest.mock import AsyncMock

    project_id = uuid4()
    user_id = "user-decline"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    pending = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relaciona Libro con Autor",
        missing_fields=[{"key": "relation.type", "critical": True, "question": "¿Qué tipo?"}],
    )
    continuation_repo.save(pending)

    decline_msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="cancela eso, no quiero hacer ninguna relación",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(decline_msg)

    provider = AsyncMock()
    provider.complete.return_value = AiResult(
        text=json.dumps({"decision": "decline", "candidate_id": str(pending.id)}),
        model_role=ModelRole.MAIN,
        model="test-model",
    )
    resolver = ContinuationResolver(ai_provider=provider)
    orchestrator = OrchestratorStub()

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=resolver,
        request_readiness=RequestReadiness(),
    )

    result = await use_case.execute(message_id=decline_msg.id)
    assert result.status == "completed"
    assert len(orchestrator.calls) == 0

    declined_cand = continuation_repo.find_by_id(pending.id)
    assert declined_cand.state == ContinuationState.DECLINED
    assert declined_cand.close_reason == ContinuationCloseReason.DECLINED


@pytest.mark.anyio
async def test_continuation_terminal_close_records_resolution_and_links_root():
    """Al completar exitosamente una aclaración, el hilo se cierra como RESOLVED con motivo resolved y vínculo raíz."""
    project_id = uuid4()
    user_id = "user-terminal-close"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    orchestrator = OrchestratorStub(response_text="Relación creada exitosamente.")
    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        continuation_resolver=ContinuationResolver(ai_provider=None),
        request_readiness=RequestReadiness(),
    )

    # Turno 1: Solicitud inicial incompleta
    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Relaciona Libro con Autor",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg1)
    await use_case.execute(message_id=msg1.id)

    pending = continuation_repo.find_by_root_message_id(msg1.id)
    assert pending is not None
    assert pending.root_message_id == msg1.id
    assert pending.state == ContinuationState.AWAITING_INPUT

    # Turno 2: Usuario aclara tipo
    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="asociación",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg2)
    await use_case.execute(message_id=msg2.id)

    # Turno 3: Usuario aclara cardinalidades
    msg3 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="1 en Autor y 0..* en Libro",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg3)
    await use_case.execute(message_id=msg3.id)

    # Hilo cerrado en estado RESOLVED con close_reason resolved
    closed_cont = continuation_repo.find_by_id(pending.id)
    assert closed_cont.state == ContinuationState.RESOLVED
    assert closed_cont.outcome == ContinuationOutcome.SUCCESS
    assert closed_cont.close_reason == ContinuationCloseReason.RESOLVED
    assert closed_cont.root_message_id == msg1.id


@pytest.mark.anyio
async def test_continuation_explicit_retry_preserves_confirmed_operations():
    """Un reintento explícito tras fallo parcial no vuelve a ejecutar operaciones ya confirmadas."""
    from app.modules.assistant.application.services.continuation.residual_plan_builder import (
        ResidualPlanBuilder,
    )

    t1_id = str(uuid4())
    t2_id = str(uuid4())
    prior_plan_dict = {
        "version": 1,
        "goal": "Crear Pedido y asociarlo a Cliente",
        "status": "failed",
        "tasks": [
            {
                "id": t1_id,
                "objective": "Crear clase Pedido",
                "kind": "mutation",
                "status": "completed",
                "depends_on": [],
                "operation_ids": ["op-1"],
                "result_refs": [{"id": "ped-1", "type": "class", "name": "Pedido"}],
            },
            {
                "id": t2_id,
                "objective": "Crear relación Pedido con Cliente",
                "kind": "mutation",
                "status": "failed",
                "depends_on": [t1_id],
                "operation_ids": ["op-2"],
                "result_refs": [],
            },
        ],
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "task_id": t1_id,
                "tool_name": "diagram_class_tools",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"id": "ped-1", "type": "class", "name": "Pedido"}],
            }
        ],
        "limits": {},
        "created_at": "2026-11-05T00:00:00Z",
        "updated_at": "2026-11-05T00:00:00Z",
    }

    builder = ResidualPlanBuilder()
    residual = builder.build(
        prior_plan_dict,
        new_goal="Reintento: Asociar Pedido con Cliente",
    )

    assert residual is not None
    assert len(residual.tasks) == 1
    assert residual.tasks[0]["id"] == t2_id
    assert residual.tasks[0]["status"] == "pending"
    assert "op-1" not in residual.tasks[0]["operation_ids"]
    assert len(residual.operation_ledger) == 1
    assert residual.operation_ledger[0]["operation_id"] == "op-1"
    assert residual.operation_ledger[0]["status"] == "applied"


@pytest.mark.anyio
async def test_process_agent_message_explicit_retry_with_additional_request(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", True)

    project_id = uuid4()
    user_id = "user-123"
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()

    t1_id = str(uuid4())
    t2_id = str(uuid4())
    plan_dict = {
        "version": 1,
        "goal": "Crear Factura y asociar Cliente",
        "status": "partial",
        "tasks": [
            {
                "id": t1_id,
                "objective": "Crear clase Factura",
                "kind": "mutation",
                "status": "completed",
                "depends_on": [],
                "operation_ids": ["op-1"],
                "result_refs": [{"id": "f-1", "type": "class", "name": "Factura"}],
            },
            {
                "id": t2_id,
                "objective": "Crear relación Factura con Cliente",
                "kind": "mutation",
                "status": "failed",
                "depends_on": [t1_id],
                "operation_ids": ["op-2"],
                "result_refs": [],
            },
        ],
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "task_id": t1_id,
                "tool_name": "diagram_class_tools",
                "action_kind": "CREATE_CLASS",
                "status": "applied",
                "entity_refs": [{"id": "f-1", "type": "class", "name": "Factura"}],
            }
        ],
        "limits": {},
        "created_at": "2026-11-05T00:00:00Z",
        "updated_at": "2026-11-05T00:00:00Z",
    }

    # Mensaje 1 (raíz) ya falló parcialmente
    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crear Factura y asociar Cliente",
        status=AgentMessageStatus.PARTIAL,
        plan=plan_dict,
    )
    message_repo.add(msg1)

    # Continuación residual generada por el fallo de msg1
    cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=msg1.id,
        source_plan_message_id=msg1.id,
        effective_request="Crear Factura y asociar Cliente",
        outcome=ContinuationOutcome.PARTIAL,
        purpose=ContinuationPurpose.RESIDUAL_RETRY,
        missing_fields=(),
    )
    continuation_repo.save(cont)

    # Mensaje 2: el usuario reintenta y añade una instrucción
    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="reintenta y agrega atributo total a Factura",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg2)

    orchestrator = OrchestratorStub()
    readiness = RequestReadiness()
    dialog_mgr = DialogManager(
        continuation_repository=continuation_repo,
        turn_interpreter=TurnInterpreter(),
        dialog_policy=DialogPolicy(),
        context_assembler=ContextAssembler(),
    )

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        dialog_manager=dialog_mgr,
        request_readiness=readiness,
    )

    result = await use_case.execute(message_id=msg2.id)
    assert result.status == "completed"

    # Verificar que el orchestrator recibió el residual_plan esperado
    assert len(orchestrator.calls) == 1
    ctx = orchestrator.calls[0]
    assert ctx.residual_plan is not None
    residual_plan = ctx.residual_plan
    task_ids = [t["id"] for t in residual_plan.tasks]
    assert t1_id not in task_ids  # Tarea 1 completada no se repite
    assert t2_id in task_ids      # Tarea 2 fallida se reintenta
    assert any("additional-request" in tid for tid in task_ids)  # Nueva tarea agregada
    # Operación confirmada conservada en ledger
    assert len(residual_plan.operation_ledger) == 1
    assert residual_plan.operation_ledger[0]["operation_id"] == "op-1"

    # La continuación residual fue cerrada
    closed_cont = continuation_repo.find_by_id(cont.id)
    assert closed_cont.state == ContinuationState.RESOLVED
    assert closed_cont.close_reason == ContinuationCloseReason.RESOLVED

    # El mensaje raíz msg1 permanece en su estado terminal y no fue reabierto
    root_msg = message_repo.find_by_id(msg1.id)
    assert root_msg.status == AgentMessageStatus.PARTIAL

