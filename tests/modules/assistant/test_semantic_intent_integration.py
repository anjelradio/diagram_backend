"""Pruebas de integración del Enrutador Semántico de Intención con ProcessAgentMessageUseCase."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiRequest,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.intent import (
    SemanticCategory,
    SemanticIntentRouter,
)
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
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


class MockAiProvider(AiProvider):
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = responses or []
        self.recorded_requests: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.recorded_requests.append(request)
        if self.responses:
            data = self.responses.pop(0)
        else:
            data = {
                "category": "DIRECT_ACTION",
                "reasoning": "Default mock response",
                "resolved_goal": "Acción directa por defecto",
                "requires_mutation": True,
                "missing_info": None,
                "clarification_question": None,
            }
        return AiResult(
            text=json.dumps(data, ensure_ascii=False),
            model_role=ModelRole.MAIN,
            model="mock-model",
            completed=True,
        )


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
        for c in self.continuations.values():
            if c.project_id == project_id and c.user_id == user_id and c.state in (
                ContinuationState.AWAITING_INPUT,
                ContinuationState.READY,
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
        result = [
            c
            for c in self.continuations.values()
            if c.project_id == project_id
            and c.user_id == user_id
            and c.state in (ContinuationState.AWAITING_INPUT, ContinuationState.READY)
        ]
        return result[:limit]

    def find_active_candidates(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = 3,
        now: datetime | None = None,
    ) -> list[AgentContinuation]:
        return self.list_active_candidates(project_id=project_id, user_id=user_id, limit=limit)

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
        if c.version == expected_version and c.state in (
            ContinuationState.AWAITING_INPUT,
            ContinuationState.READY,
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

    def add(self, message: AgentMessage) -> None:
        self.messages[message.id] = message

    def find_by_id(self, message_id: UUID) -> AgentMessage | None:
        return self.messages.get(message_id)

    def save_terminal(self, message: AgentMessage) -> bool:
        self.messages[message.id] = message
        return True

    def save_plan_progress(self, message: AgentMessage) -> bool:
        self.messages[message.id] = message
        return True

    def link_root_message(self, *, message_id: UUID, root_message_id: UUID) -> bool:
        msg = self.messages.get(message_id)
        if msg:
            msg.root_message_id = root_message_id
            return True
        return False


class AccessPolicyStub:
    def ensure_read_access(self, project_id: UUID, user_id: str) -> None:
        pass


class ContextBuilderStub:
    def build(self, message: AgentMessage) -> Any:
        return SimpleNamespace(
            image_url=message.image_url,
            prompt=message.prompt,
            effective_request=message.prompt,
            authorized_mode=None,
            recent_turns=None,
            is_compound=False,
            visual_needs_image=False,
        )


class OrchestratorStub:
    def __init__(self, response_text: str = "Operación completada con éxito."):
        self.response_text = response_text
        self.contexts_received: list[Any] = []

    async def respond_with_progress(self, context, on_plan_progress, on_activity):
        self.contexts_received.append(context)
        return AiResult(
            text=self.response_text,
            model_role=ModelRole.MAIN,
            model="mock-orchestrator",
            completed=True,
            metadata={"status": "success"},
        )


class UnitOfWorkStub:
    def rollback(self):
        pass

    def commit(self):
        pass


@pytest.mark.anyio
async def test_direct_action_routes_cleanly():
    """1. Acción directa autosuficiente: se clasifica como DIRECT_ACTION con requires_mutation=True."""
    mock_provider = MockAiProvider([
        {
            "category": "DIRECT_ACTION",
            "reasoning": "El usuario solicita explícitamente crear una clase Factura.",
            "resolved_goal": "Crear la clase Factura con atributos id, numero y fecha.",
            "requires_mutation": True,
            "missing_info": None,
            "clarification_question": None,
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    orchestrator = OrchestratorStub("Clase Factura creada exitosamente.")

    msg = AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="Crea la clase Factura con id, numero y fecha",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
        class_provider=lambda proj_id: {"Cliente": "1", "Pedido": "2"},
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    ctx = orchestrator.contexts_received[0]
    assert "Factura" in ctx.prompt
    assert ctx.authorized_mode == "execute"


@pytest.mark.anyio
async def test_anaphora_decontextualization_and_continuation_resolution():
    """2. Anáfora ('Aplica esa generalización'): el router reescribe a la orden canónica explícita y resuelve la continuación."""
    project_id = uuid4()
    user_id = "user-1"
    root_id = uuid4()

    continuation_repo = InMemoryContinuationRepository()
    active_cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=root_id,
        source_plan_message_id=root_id,
        effective_request="Propuesta de herencia entre Usuario y Administrador",
        outcome=ContinuationOutcome.AWAITING_INPUT,
        purpose=ContinuationPurpose.CLARIFICATION,
    )
    continuation_repo.save(active_cont)

    mock_provider = MockAiProvider([
        {
            "category": "CONTINUATION_OR_ANAPHORA",
            "reasoning": "El usuario se refiere a la generalización discutida en el turno anterior.",
            "resolved_goal": "Crear una relación de herencia entre Usuario (superclase) y Administrador (subclase).",
            "requires_mutation": True,
            "missing_info": None,
            "clarification_question": None,
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    orchestrator = OrchestratorStub("Relación de herencia creada.")

    msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Aplica esa generalización",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
        class_provider=lambda pid: {"Usuario": "1", "Administrador": "2"},
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    assert len(orchestrator.contexts_received) == 1
    ctx = orchestrator.contexts_received[0]
    assert "Crear una relación de herencia entre Usuario (superclase) y Administrador (subclase)." in ctx.prompt
    assert ctx.authorized_mode == "execute"

    # Verificar que la continuación se resolvió exitosamente
    resolved_cont = continuation_repo.find_by_id(active_cont.id)
    assert resolved_cont.state == ContinuationState.RESOLVED
    assert resolved_cont.outcome == ContinuationOutcome.SUCCESS


@pytest.mark.anyio
async def test_compound_action_sets_compound_flag():
    """3. Acción compuesta ('Aplica esa relación y además crea Proveedor'): se desambigua y marca is_compound."""
    mock_provider = MockAiProvider([
        {
            "category": "COMPOUND_ACTION",
            "reasoning": "Combina la herencia previa con la creación de una nueva clase Proveedor.",
            "resolved_goal": "Crear una relación de herencia entre Usuario y Administrador, y crear la clase Proveedor con atributo rfc.",
            "requires_mutation": True,
            "missing_info": None,
            "clarification_question": None,
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    orchestrator = OrchestratorStub("Plan de tareas ejecutado.")

    msg = AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="Aplica esa relación y además crea la clase Proveedor con rfc",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    ctx = orchestrator.contexts_received[0]
    assert ctx.is_compound is True
    assert ctx.authorized_mode == "execute"


@pytest.mark.anyio
async def test_needs_more_context_creates_continuation_and_asks_user():
    """4. Ambigüedad ('Relaciona las clases'): la IA decide solicitar contexto, no llama al orquestador y formula la pregunta."""
    mock_provider = MockAiProvider([
        {
            "category": "NEEDS_MORE_CONTEXT",
            "reasoning": "Hay 4 clases en el diagrama y no se especificó cuáles relacionar ni qué tipo de relación.",
            "resolved_goal": "Relacionar clases del diagrama.",
            "requires_mutation": False,
            "missing_info": ["clase_origen", "clase_destino", "tipo_relacion"],
            "clarification_question": "¿Entre cuáles de las clases existentes (Usuario, Administrador, Pedido, Producto) deseas crear la relación y de qué tipo (asociación, herencia)?",
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    orchestrator = OrchestratorStub()

    project_id = uuid4()
    msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id="user-1",
        prompt="Relaciona las clases",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
        class_provider=lambda pid: {"Usuario": "1", "Administrador": "2", "Pedido": "3", "Producto": "4"},
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    # El orquestador NO debe haberse llamado (0 mutaciones, 0 plan de acción)
    assert len(orchestrator.contexts_received) == 0
    # La respuesta es la pregunta de clarificación
    assert "¿Entre cuáles de las clases existentes" in result.response_markdown

    # Se creó una continuación en estado AWAITING_INPUT
    candidates = continuation_repo.list_active_candidates(project_id=project_id, user_id="user-1")
    assert len(candidates) == 1
    assert candidates[0].state == ContinuationState.AWAITING_INPUT
    assert candidates[0].purpose == ContinuationPurpose.CLARIFICATION


@pytest.mark.anyio
async def test_conceptual_consultation_routes_read_only():
    """5. Consulta teórica ('¿En UML qué relación es la más adecuada...?'): se asigna authorized_mode='read_only'."""
    mock_provider = MockAiProvider([
        {
            "category": "CONCEPTUAL_CONSULTATION",
            "reasoning": "El usuario hace una pregunta conceptual de diseño UML sobre la relación entre Administrador y Usuario.",
            "resolved_goal": "¿En UML qué relación es la más adecuada si un Administrador es un tipo especializado de Usuario?",
            "requires_mutation": False,
            "missing_info": None,
            "clarification_question": None,
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    orchestrator = OrchestratorStub("En UML, la relación más adecuada es la generalización (herencia)...")

    msg = AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="¿En UML qué relación es la más adecuada si un Administrador es un tipo especializado de Usuario?",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    assert len(orchestrator.contexts_received) == 1
    ctx = orchestrator.contexts_received[0]
    assert ctx.authorized_mode == "read_only"
    assert "generalización" in result.response_markdown


@pytest.mark.anyio
async def test_decline_or_cancel_closes_continuation():
    """6. Cancelación ('Cancela eso, déjalo así'): cierra la continuación pendiente y responde cortésmente sin llamar al orquestador."""
    project_id = uuid4()
    user_id = "user-1"
    continuation_repo = InMemoryContinuationRepository()

    cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        source_plan_message_id=uuid4(),
        effective_request="Propuesta de relación",
        outcome=ContinuationOutcome.AWAITING_INPUT,
        purpose=ContinuationPurpose.CLARIFICATION,
    )
    continuation_repo.save(cont)

    mock_provider = MockAiProvider([
        {
            "category": "DECLINE_OR_CANCEL",
            "reasoning": "El usuario indica explícitamente cancelar la propuesta.",
            "resolved_goal": "Cancelar la propuesta.",
            "requires_mutation": False,
            "missing_info": None,
            "clarification_question": "Entendido, se ha cancelado la solicitud pendiente.",
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    orchestrator = OrchestratorStub()

    msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Cancela eso, déjalo así",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    assert len(orchestrator.contexts_received) == 0
    assert "cancelado" in result.response_markdown

    # La continuación debe quedar cerrada con DECLINED
    updated_cont = continuation_repo.find_by_id(cont.id)
    assert updated_cont.state == ContinuationState.DECLINED
    assert updated_cont.close_reason == ContinuationCloseReason.DECLINED


@pytest.mark.anyio
async def test_colloquial_slang_and_idiomatic_expressions():
    """7. Variaciones coloquiales en español ('Dale con eso, conéctalas ya', 'Me convenciste'): el LLM desambigua sin problemas sintácticos."""
    mock_provider = MockAiProvider([
        {
            "category": "CONTINUATION_OR_ANAPHORA",
            "reasoning": "La frase 'Dale con eso, conéctalas ya' es una aceptación coloquial de la relación discutida.",
            "resolved_goal": "Crear una relación de herencia entre Usuario y Administrador.",
            "requires_mutation": True,
            "missing_info": None,
            "clarification_question": None,
        }
    ])
    router = SemanticIntentRouter(ai_provider=mock_provider)
    message_repo = MessageRepositoryStub()
    continuation_repo = InMemoryContinuationRepository()
    orchestrator = OrchestratorStub("Relación conectada.")

    msg = AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="Dale con eso, conéctalas ya",
        status=AgentMessageStatus.RUNNING,
    )
    message_repo.add(msg)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=None,
        continuation_repository=continuation_repo,
        project_access_policy=AccessPolicyStub(),
        context_builder=ContextBuilderStub(),
        orchestrator=orchestrator,
        uow=UnitOfWorkStub(),
        semantic_intent_router=router,
    )

    result = await use_case.execute(message_id=msg.id)

    assert result.status == "completed"
    assert len(orchestrator.contexts_received) == 1
    assert "Crear una relación de herencia entre Usuario y Administrador." in orchestrator.contexts_received[0].prompt
