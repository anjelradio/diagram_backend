"""Pruebas del gestor de diálogo estructurado (Amazon Lex style) basadas en el corpus canónico."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    AgentConversationReader,
    RecentExchange,
)
from app.modules.assistant.application.services.dialog.context_assembler import ContextAssembler
from app.modules.assistant.application.services.dialog.dialog_manager import DialogManager, DialogTurnResult, extract_proposals_from_recent_exchanges
from app.modules.assistant.application.services.dialog.dialog_policy import DialogPolicy
from app.modules.assistant.application.services.diagram.grounded_recommendation import GroundedRecommendationService
from app.modules.assistant.application.services.dialog.turn_interpreter import TurnInterpreter
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState, Proposal, SlotProvenance
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.diagram.application.ports.readers.agent_diagram_reader import (
    DiagramElementDetailDto, DiagramElementReferenceDto, DiagramElementSearchDto,
)
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.repositories.agent_continuation_repository import AgentContinuationRepository
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class InMemoryContinuationRepository(AgentContinuationRepository):
    """Repositorio en memoria para pruebas de ciclo de vida del diálogo."""

    def __init__(self) -> None:
        self.continuations: dict[str, AgentContinuation] = {}

    def find_by_id(self, continuation_id):
        return self.continuations.get(str(continuation_id))

    def find_by_root_message_id(self, root_message_id):
        for c in self.continuations.values():
            if c.root_message_id == root_message_id:
                return c
        return None

    def find_active_by_scope(self, *, project_id, user_id, now=None):
        current_time = now or datetime.now(timezone.utc)
        active = [
            c for c in self.continuations.values()
            if c.project_id == project_id
            and c.user_id == user_id
            and c.purpose == ContinuationPurpose.CLARIFICATION
            and c.state in (ContinuationState.AWAITING_INPUT, ContinuationState.READY, ContinuationState.CLAIMED)
            and c.expires_at > current_time
        ]
        active.sort(key=lambda c: (c.updated_date, c.created_date), reverse=True)
        return active[0] if active else None

    def list_active_candidates(self, *, project_id, user_id, limit=3, purpose=None, now=None):
        current_time = now or datetime.now(timezone.utc)
        purpose_val = (
            purpose.value if isinstance(purpose, ContinuationPurpose) else str(purpose) if purpose else None
        )
        res = [
            c for c in self.continuations.values()
            if c.project_id == project_id
            and c.user_id == user_id
            and c.state.value in ("awaiting_input", "ready")
            and c.expires_at > current_time
            and (purpose_val is None or c.purpose.value == purpose_val)
        ]
        res.sort(key=lambda c: (c.updated_date, c.created_date), reverse=True)
        return res[:limit]

    def save(self, continuation: AgentContinuation) -> None:
        self.continuations[str(continuation.id)] = continuation

    def claim_atomic(self, *, continuation_id, expected_version, by_message_id, now=None):
        c = self.continuations.get(str(continuation_id))
        if c and c.version == expected_version:
            claimed = c.claim(by_message_id=by_message_id, expected_version=expected_version)
            self.continuations[str(continuation_id)] = claimed
            return claimed
        return None

    def resolve_atomic(
        self,
        *,
        continuation_id,
        expected_version,
        outcome=ContinuationOutcome.SUCCESS,
        close_reason=ContinuationCloseReason.RESOLVED,
        now=None,
    ):
        c = self.continuations.get(str(continuation_id))
        if not c or c.version != expected_version:
            return None
        resolved = c.resolve(outcome=outcome, close_reason=close_reason)
        self.continuations[str(continuation_id)] = resolved
        return resolved

    def close_claimed_by_message(
        self,
        *,
        message_id,
        close_reason=ContinuationCloseReason.CANCELLED,
        now=None,
    ):
        count = 0
        for cid, c in list(self.continuations.items()):
            if c.claimed_by_message_id == message_id and c.state == ContinuationState.CLAIMED:
                self.continuations[cid] = c.close(close_reason)
                count += 1
        return count


class InMemoryConversationReader(AgentConversationReader):
    """Lector en memoria para pruebas de diálogo con historial reciente."""

    def __init__(self, entries: list[Any] | None = None) -> None:
        self.entries: list[tuple[RecentExchange, UUID | None, str | None]] = []
        for item in (entries or []):
            if isinstance(item, tuple):
                self.entries.append(item)
            else:
                self.entries.append((item, None, None))

    def read_conversation_page(self, **kwargs):
        raise NotImplementedError

    def read_message_detail(self, **kwargs):
        raise NotImplementedError

    def get_recent_exchanges(
        self,
        *,
        project_id: UUID,
        user_id: str,
        exclude_message_id: UUID | None = None,
        before: datetime | None = None,
        limit: int = 3,
        exclude_superseded: bool = False,
    ) -> list[RecentExchange]:
        res = []
        for ex, pid, uid in self.entries:
            if pid is not None and pid != project_id:
                continue
            if uid is not None and uid != user_id:
                continue
            if exclude_message_id is not None and ex.message_id == exclude_message_id:
                continue
            if exclude_superseded and getattr(ex, "is_superseded", False):
                continue
            res.append(ex)
        return res[:limit]


@pytest.mark.anyio
async def test_grouped_relations_keep_partial_answers_on_their_own_pairs():
    manager = DialogManager(continuation_repository=InMemoryContinuationRepository())
    project_id = uuid4()

    async def send(prompt):
        return await manager.handle_turn(message=AgentMessage.register(
            id=uuid4(), project_id=project_id, user_id="user", prompt=prompt,
        ))

    first = await send("Crea una relación entre A y B. También crea una relación entre C y D.")
    assert first.status == "awaiting_input"
    assert "A y la clase B" in first.assistant_message
    assert "C y la clase D" in first.assistant_message

    partial = await send("Para A y B quiero herencia, y para C y D composición.")
    assert partial.status == "awaiting_input"
    assert "padre" in partial.assistant_message and "contenedora" in partial.assistant_message

    ready = await send("Para A y B A es padre, y para C y D C contiene a D.")
    assert ready.status == "ready_to_execute"
    assert "padre es A" in ready.effective_request
    assert "C es el contenedor" in ready.effective_request
    assert ready.continuation.root_message_id == first.continuation.root_message_id


@pytest.mark.anyio
async def test_acceptance_keeps_extra_instruction_and_skips_history():
    reader = Mock()
    manager = DialogManager(
        continuation_repository=InMemoryContinuationRepository(), conversation_reader=reader
    )
    project_id = uuid4()

    async def send(prompt):
        return await manager.handle_turn(message=AgentMessage.register(
            id=uuid4(), project_id=project_id, user_id="user", prompt=prompt,
        ))

    await send("Crea una relación entre Producto y Categoría")
    proposal = await send("¿Qué relación me recomiendas?")
    assert "Opción A" in proposal.assistant_message
    ready = await send("Implementa la opción A y además crea una clase llamada Árbol")
    assert ready.status == "ready_to_execute"
    assert "Producto" in ready.effective_request and "Categoría" in ready.effective_request
    assert "crea una clase llamada Árbol" in ready.effective_request
    reader.get_recent_exchanges.assert_not_called()


@pytest.mark.anyio
async def test_resolved_class_reaches_orchestrator_with_immutable_context():
    from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
    from app.modules.assistant.application.services.context_builder import ContextBuilder
    from app.modules.assistant.application.use_cases.process_agent_message import ProcessAgentMessageUseCase

    project_id = uuid4()
    continuation_repository = InMemoryContinuationRepository()
    message_repository = Mock()
    message_repository.save_terminal.return_value = True
    orchestrator = Mock(spec=["respond"])
    orchestrator.respond = AsyncMock(return_value=AiResult(
        text="Clase creada.", model_role=ModelRole.MAIN, model="test", completed=True,
    ))
    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repository,
        memory_repository=None,
        project_access_policy=Mock(),
        context_builder=ContextBuilder(),
        orchestrator=orchestrator,
        uow=Mock(),
        continuation_repository=continuation_repository,
        dialog_manager=DialogManager(continuation_repository=continuation_repository),
    )

    async def send(prompt):
        message = AgentMessage(
            id=uuid4(), project_id=project_id, user_id="user", prompt=prompt,
            status=AgentMessageStatus.RUNNING,
        )
        message_repository.find_by_id.return_value = message
        await use_case.execute(message_id=message.id, project_id=project_id, user_id="user")
        return message

    root = await send("Crea una clase")
    orchestrator.respond.assert_not_awaited()
    reply = await send("Casa")
    assert reply.status is AgentMessageStatus.COMPLETED
    assert reply.root_message_id == root.id
    assert orchestrator.respond.await_args.args[0].prompt == "Crea una clase llamada Casa."
    assert continuation_repository.find_by_root_message_id(root.id).state is ContinuationState.RESOLVED


@pytest.fixture
def corpus_data():
    fixture_path = Path(__file__).parent / "fixtures" / "dialog_conversation_corpus.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.anyio
async def test_scenario_1_rel_missing_type_dry_answer():
    """Turno 1: petición sin tipo -> elicit_slots
    Turno 2: respuesta seca 'herencia' -> elicit_slots (falta dirección)
    Turno 3: 'Usuario es la clase padre' -> fulfill
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # Turno 1
    turn1 = await interpreter.interpret(
        user_message="Haz una relación entre la clase Usuario y la clase Perfil",
        dialog_state=state,
    )
    assert turn1.user_act == "new_request"
    assert turn1.proposed_action == "CREATE_RELATION"
    assert turn1.slots["relation.source_class"] == "Usuario"
    assert turn1.slots["relation.target_class"] == "Perfil"

    decision1 = policy.decide(turn=turn1, state=state)
    assert decision1.assistant_act == "elicit_slots"
    assert any(s.key == "relation.type" for s in state.active_frame.missing_slots)

    # Turno 2: Respuesta seca
    turn2 = await interpreter.interpret(
        user_message="herencia",
        dialog_state=state,
    )
    assert turn2.user_act == "provide_slots"
    assert turn2.slots.get("relation.type") == "GENERALIZATION"

    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "elicit_slots"
    assert any(s.key == "relation.direction" for s in state.active_frame.missing_slots)

    # Turno 3: Dirección
    turn3 = await interpreter.interpret(
        user_message="Usuario es la clase padre",
        dialog_state=state,
    )
    assert turn3.slots.get("relation.superclass") == "Usuario"

    decision3 = policy.decide(turn=turn3, state=state)
    assert decision3.assistant_act == "fulfill"
    assert decision3.resolved_request is not None
    assert "herencia" in decision3.resolved_request.lower() or "generalización" in decision3.resolved_request.lower()
    assert "Usuario" in decision3.resolved_request


@pytest.mark.anyio
async def test_scenario_2_rel_missing_multiple_partial_answers():
    """Turno 1: 'Conecta la clase Cliente con la clase Pedido' -> elicit_slots
    Turno 2: 'que sea una asociación' -> elicit_slots (faltan cardinalidades)
    Turno 3: '1 a muchos, 1 en Cliente y 0..* en Pedido' -> fulfill
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # Turno 1
    turn1 = await interpreter.interpret(
        user_message="Conecta la clase Cliente con la clase Pedido",
        dialog_state=state,
    )
    decision1 = policy.decide(turn=turn1, state=state)
    assert decision1.assistant_act == "elicit_slots"

    # Turno 2
    turn2 = await interpreter.interpret(
        user_message="que sea una asociación",
        dialog_state=state,
    )
    assert turn2.slots.get("relation.type") == "ASSOCIATION"
    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "elicit_slots"
    assert any(s.key == "relation.endpoint_cardinalities" for s in state.active_frame.missing_slots)

    # Turno 3
    turn3 = await interpreter.interpret(
        user_message="1 a muchos, 1 en Cliente y 0..* en Pedido",
        dialog_state=state,
    )
    assert turn3.slots.get("relation.source_cardinality") == "1"
    assert turn3.slots.get("relation.target_cardinality") == "0..*"

    decision3 = policy.decide(turn=turn3, state=state)
    assert decision3.assistant_act == "fulfill"
    assert "asociación" in decision3.resolved_request.lower()


@pytest.mark.anyio
async def test_scenario_3_rel_recommendation_then_accept():
    """Turno 1: 'Crea una relación entre Factura y DetalleFactura' -> elicit_slots
    Turno 2: '¿cuál relación tú me recomiendas?' -> consult_with_proposal (recomienda COMPOSITION)
    Turno 3: 'ok, hazlo' -> fulfill con COMPOSITION y Factura whole / DetalleFactura part
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # Turno 1
    turn1 = await interpreter.interpret(
        user_message="Crea una relación entre Factura y DetalleFactura",
        dialog_state=state,
    )
    policy.decide(turn=turn1, state=state)

    # Turno 2
    turn2 = await interpreter.interpret(
        user_message="¿cuál relación tú me recomiendas?",
        dialog_state=state,
    )
    assert turn2.user_act == "consult"
    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "consult_with_proposal"
    assert len(state.proposals) >= 1
    proposal = state.proposals[-1]
    assert proposal.slots.get("relation.type") == "COMPOSITION"

    # Turno 3: Aceptación
    turn3 = await interpreter.interpret(
        user_message="ok, hazlo",
        dialog_state=state,
    )
    assert turn3.user_act == "accept_proposal"
    decision3 = policy.decide(turn=turn3, state=state)
    assert decision3.assistant_act == "fulfill"
    assert "composición" in decision3.resolved_request.lower()
    assert "Factura" in decision3.resolved_request
    assert "DetalleFactura" in decision3.resolved_request


@pytest.mark.anyio
async def test_scenario_4_attr_missing_class():
    """Turno 1: 'Agrega un atributo llamado email' -> elicit_slots (falta target_class)
    Turno 2: 'En la clase Usuario' -> fulfill
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    turn1 = await interpreter.interpret(
        user_message="Agrega un atributo llamado email",
        dialog_state=state,
    )
    assert turn1.slots.get("attribute.name") == "email"
    decision1 = policy.decide(turn=turn1, state=state)
    assert decision1.assistant_act == "elicit_slots"

    turn2 = await interpreter.interpret(
        user_message="En la clase Usuario",
        dialog_state=state,
    )
    assert turn2.slots.get("attribute.target_class") == "Usuario"
    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "fulfill"
    assert "email" in decision2.resolved_request
    assert "Usuario" in decision2.resolved_request


@pytest.mark.anyio
async def test_scenario_5_correction_in_middle_of_dialog():
    """Turno 1: 'Relaciona Producto y Categoria' -> elicit_slots
    Turno 2: 'asociación' -> elicit_slots
    Turno 3: 'no, mejor que sea agregación donde Categoria contiene a Producto' -> fulfill
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    turn1 = await interpreter.interpret(
        user_message="Relaciona Producto y Categoria",
        dialog_state=state,
    )
    policy.decide(turn=turn1, state=state)

    turn2 = await interpreter.interpret(
        user_message="asociación",
        dialog_state=state,
    )
    policy.decide(turn=turn2, state=state)

    turn3 = await interpreter.interpret(
        user_message="no, mejor que sea agregación donde Categoria contiene a Producto",
        dialog_state=state,
    )
    assert turn3.user_act == "correct"
    assert turn3.slots.get("relation.type") == "AGGREGATION"
    assert turn3.slots.get("relation.whole") == "Categoria"
    assert turn3.slots.get("relation.part") == "Producto"

    decision3 = policy.decide(turn=turn3, state=state)
    assert decision3.assistant_act == "fulfill"
    assert "agregación" in decision3.resolved_request.lower()


@pytest.mark.anyio
async def test_scenario_6_explicit_decline():
    """Turno 1: 'Crea una relación entre Proveedor e Insumo' -> elicit_slots
    Turno 2: 'cancela, ya no hagas nada' -> decline
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    turn1 = await interpreter.interpret(
        user_message="Crea una relación entre Proveedor e Insumo",
        dialog_state=state,
    )
    policy.decide(turn=turn1, state=state)

    turn2 = await interpreter.interpret(
        user_message="cancela, ya no hagas nada",
        dialog_state=state,
    )
    assert turn2.user_act == "decline"
    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "decline"
    assert "cancelado" in decision2.assistant_message.lower()


@pytest.mark.anyio
async def test_dialog_manager_end_to_end_multiturn():
    """Verifica que DialogManager persiste estado entre turnos a través del repositorio."""
    repo = InMemoryContinuationRepository()
    manager = DialogManager(continuation_repository=repo)
    project_id = uuid4()
    user_id = "test_user_alexa"

    # Mensaje 1
    msg1 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Haz una relación entre la clase Usuario y la clase Perfil",
        status=AgentMessageStatus.RUNNING,
    )
    res1 = await manager.handle_turn(message=msg1)
    assert res1.status == "awaiting_input"
    assert res1.assistant_act == "elicit_slots"
    assert len(repo.continuations) == 1

    # Mensaje 2 (Respuesta corta: herencia)
    msg2 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="herencia",
        status=AgentMessageStatus.RUNNING,
    )
    res2 = await manager.handle_turn(message=msg2)
    assert res2.status == "awaiting_input"
    assert res2.assistant_act == "elicit_slots"
    persisted = list(repo.continuations.values())[0]
    frame_dict = persisted.dialog_state["frames"][0]
    assert frame_dict["slots"]["relation.type"]["value"] == "GENERALIZATION"

    # Mensaje 3 (Completar padre: Usuario es la clase padre)
    msg3 = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Usuario es la clase padre",
        status=AgentMessageStatus.RUNNING,
    )
    res3 = await manager.handle_turn(message=msg3)
    assert res3.status == "ready_to_execute"
    assert res3.assistant_act == "fulfill"
    assert res3.effective_request is not None
    assert "herencia" in res3.effective_request.lower() or "generalización" in res3.effective_request.lower()


@pytest.mark.anyio
async def test_process_agent_message_dialog_manager_flag_enabled(monkeypatch):
    """Verifica la integración dentro de ProcessAgentMessageUseCase con el flag activado."""
    from app.core.config import settings
    from app.modules.assistant.application.use_cases.process_agent_message import ProcessAgentMessageUseCase
    from unittest.mock import MagicMock, AsyncMock

    monkeypatch.setattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", True)

    project_id = uuid4()
    user_id = "test_user_flag"
    msg_id = uuid4()

    msg = AgentMessage(
        id=msg_id,
        project_id=project_id,
        user_id=user_id,
        prompt="Haz una relación entre la clase Usuario y la clase Perfil",
        status=AgentMessageStatus.RUNNING,
    )

    msg_repo = MagicMock()
    msg_repo.find_by_id.return_value = msg
    msg_repo.save_terminal.return_value = True

    cont_repo = InMemoryContinuationRepository()
    uow = MagicMock()
    policy = MagicMock()
    policy.ensure_read_access.return_value = None

    context_builder = MagicMock()
    orchestrator = MagicMock()

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=policy,
        context_builder=context_builder,
        orchestrator=orchestrator,
        uow=uow,
        continuation_repository=cont_repo,
        dialog_manager=DialogManager(continuation_repository=cont_repo),
    )

    result = await use_case.execute(message_id=msg_id, project_id=project_id, user_id=user_id)

    assert result.status == AgentMessageStatus.COMPLETED.value
    # Debe haber guardado una continuación con estado de diálogo
    active = cont_repo.list_active_candidates(project_id=project_id, user_id=user_id)
    assert len(active) == 1
    assert active[0].dialog_state is not None
    assert "relation.type" in [s["key"] for s in active[0].missing_fields]
    assert msg.plan["outcome"] == "awaiting_input"
    assert msg.plan["assistant_act"] == "elicit_slots"
    assert msg.plan["dialog_state"] == active[0].dialog_state


@pytest.mark.anyio
async def test_process_agent_message_dialog_manager_flag_disabled(monkeypatch):
    """Verifica que si el flag está desactivado (False), no se invoca DialogManager."""
    from app.core.config import settings
    from app.modules.assistant.application.use_cases.process_agent_message import ProcessAgentMessageUseCase
    from unittest.mock import MagicMock

    monkeypatch.setattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", False)

    project_id = uuid4()
    user_id = "test_user_disabled"
    msg_id = uuid4()

    msg = AgentMessage(
        id=msg_id,
        project_id=project_id,
        user_id=user_id,
        prompt="Hola mundo",
        status=AgentMessageStatus.RUNNING,
    )

    msg_repo = MagicMock()
    msg_repo.find_by_id.return_value = msg
    msg_repo.save_terminal.return_value = True

    mock_dialog_mgr = MagicMock()

    use_case = ProcessAgentMessageUseCase(
        message_repository=msg_repo,
        memory_repository=None,
        project_access_policy=MagicMock(),
        context_builder=MagicMock(),
        orchestrator=MagicMock(),
        uow=MagicMock(),
        continuation_repository=InMemoryContinuationRepository(),
        dialog_manager=mock_dialog_mgr,
    )
    use_case.orchestrator.respond = MagicMock()
    use_case.orchestrator.respond.return_value = MagicMock(text="Respuesta legacy", completed=True, metadata={})
    use_case.context_builder.build.return_value = MagicMock()

    await use_case.execute(message_id=msg_id, project_id=project_id, user_id=user_id)

    # El dialog manager no debe haber sido llamado
    assert mock_dialog_mgr.handle_turn.call_count == 0


@pytest.mark.anyio
async def test_dialog_manager_spanish_accented_recommendation_and_acceptance(monkeypatch):
    """Verifica el flujo exacto de los logs: consulta de recomendación con acentos en español,
    deduplicación de candidatos obsoletos y posterior aceptación de la propuesta."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_DIALOG_MANAGER_ENABLED", True)

    project_id = uuid4()
    user_id = "user_log_scenario"

    cont_repo = InMemoryContinuationRepository()

    # Simular acumulación de un candidato previo obsoleto y el candidato activo actual
    stale_cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relación antigua",
        resolved_facts=[],
        missing_fields=[{"key": "relation.type", "critical": True}],
    )
    stale_cont.updated_date = datetime.now(timezone.utc) - timedelta(minutes=5)
    stale_cont.created_date = datetime.now(timezone.utc) - timedelta(minutes=5)
    cont_repo.save(stale_cont)

    # Frame activo con acento en 'Categoría'
    active_state = DialogState()
    frame = DialogFrame(id="fr-cat-prod", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Categoría")
    frame.set_slot("relation.target_class", "Producto")
    frame.evaluate_readiness()
    active_state.add_frame(frame)

    current_cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Crea relación entre Categoría y Producto",
        resolved_facts=[
            {"key": "relation.source_class", "value": "Categoría"},
            {"key": "relation.target_class", "value": "Producto"},
        ],
        missing_fields=[{"key": "relation.type", "critical": True, "question": "¿Qué tipo?"}],
        dialog_state=active_state.to_dict(),
    )
    cont_repo.save(current_cont)

    # Inicialmente hay 2 candidatos activos
    assert len(cont_repo.list_active_candidates(project_id=project_id, user_id=user_id)) == 2

    dm = DialogManager(continuation_repository=cont_repo)

    # Turno 1: "¿Qué relación tú me recomiendas?"
    msg_rec = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="¿Qué relación tú me recomiendas?",
        status=AgentMessageStatus.RUNNING,
    )
    res_rec = await dm.handle_turn(message=msg_rec)

    # 1. Deduplicación: el candidato antiguo quedó expirado
    assert cont_repo.find_by_id(stale_cont.id).state == ContinuationState.EXPIRED
    # 2. El candidato actual sigue abierto esperando respuesta
    assert res_rec.status == "awaiting_input"
    assert res_rec.assistant_act == "consult_with_proposal"
    assert "Asociación" in res_rec.assistant_message
    assert "Categoría" in res_rec.assistant_message and "Producto" in res_rec.assistant_message

    # Turno 2: "Sí, dale"
    msg_accept = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Sí, dale",
        status=AgentMessageStatus.RUNNING,
    )
    res_accept = await dm.handle_turn(message=msg_accept)

    # 3. Propuesta aceptada -> Listo para ejecutar
    assert res_accept.status == "ready_to_execute"
    assert res_accept.assistant_act == "fulfill"
    assert "asociación" in res_accept.effective_request.lower()
    assert "Categoría" in res_accept.effective_request
    assert "Producto" in res_accept.effective_request


@pytest.mark.anyio
async def test_dialog_manager_self_sufficient_request_closes_active_continuation():
    """Si el usuario envía una petición autosuficiente independiente teniendo un hilo abierto,
    el hilo previo se cierra por cambio de tema y la nueva petición pasa a ejecución (pass_through)."""
    project_id = uuid4()
    user_id = "user_topic_change"
    cont_repo = InMemoryContinuationRepository()

    # Hilo previo esperando tipo de relación
    active_state = DialogState()
    frame = DialogFrame(id="fr-old", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Factura")
    frame.set_slot("relation.target_class", "Cliente")
    frame.evaluate_readiness()
    active_state.add_frame(frame)

    prev_cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relaciona Factura con Cliente",
        missing_fields=[{"key": "relation.type", "critical": True}],
        dialog_state=active_state.to_dict(),
    )
    cont_repo.save(prev_cont)

    dm = DialogManager(continuation_repository=cont_repo)

    # Nuevo mensaje autosuficiente de creación de clase
    new_msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crea una clase llamada Inventario",
        status=AgentMessageStatus.RUNNING,
    )
    result = await dm.handle_turn(message=new_msg)

    # Pasa directo a planificación
    assert result.status == "pass_through"

    # El hilo previo quedó cerrado con close_reason=topic_change
    closed_prev = cont_repo.find_by_id(prev_cont.id)
    assert closed_prev.close_reason == ContinuationCloseReason.TOPIC_CHANGE


@pytest.mark.anyio
async def test_explicit_topic_switch_discards_pending_relation_and_uses_new_request():
    project_id = uuid4()
    repo = InMemoryContinuationRepository()
    frame = DialogFrame(id="old", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Casa")
    frame.set_slot("relation.target_class", "Calle")
    state = DialogState()
    state.add_frame(frame)
    old = AgentContinuation.create(
        id=uuid4(), project_id=project_id, user_id="u1", root_message_id=uuid4(),
        effective_request="Relaciona Casa con Calle", dialog_state=state.to_dict(),
    )
    repo.save(old)
    manager = DialogManager(continuation_repository=repo)

    result = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="Olvídate de lo anterior y crea una clase Producto",
        status=AgentMessageStatus.RUNNING,
    ))

    assert result.status == "pass_through"
    assert result.effective_request == "crea una clase Producto"
    assert repo.find_by_id(old.id).close_reason == ContinuationCloseReason.TOPIC_CHANGE


@pytest.mark.anyio
async def test_independent_read_only_question_closes_old_objective():
    project_id = uuid4()
    repo = InMemoryContinuationRepository()
    old = AgentContinuation.create(
        id=uuid4(), project_id=project_id, user_id="u1", root_message_id=uuid4(),
        effective_request="Crea una clase", dialog_state=DialogState().to_dict(),
    )
    repo.save(old)
    result = await DialogManager(continuation_repository=repo).handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="¿Qué atributos tiene la clase Producto?", status=AgentMessageStatus.RUNNING,
    ))
    assert result.status == "ready_read_only"
    assert result.continuation is None
    assert repo.find_by_id(old.id).close_reason == ContinuationCloseReason.TOPIC_CHANGE


@pytest.mark.anyio
async def test_continue_does_not_bypass_missing_relation_fields():
    project_id = uuid4()
    repo = InMemoryContinuationRepository()
    state = DialogState()
    frame = DialogFrame(id="relation", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Producto")
    frame.set_slot("relation.target_class", "Categoria")
    state.add_frame(frame)
    repo.save(AgentContinuation.create(
        id=uuid4(), project_id=project_id, user_id="u1", root_message_id=uuid4(),
        effective_request="Relaciona Producto con Categoria", dialog_state=state.to_dict(),
    ))
    result = await DialogManager(continuation_repository=repo).handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="continúa", status=AgentMessageStatus.RUNNING,
    ))
    assert result.status == "awaiting_input"
    assert "relaci" in result.assistant_message.lower()


@pytest.mark.anyio
async def test_compound_request_waits_for_relation_details_before_creating_classes():
    repo = InMemoryContinuationRepository()
    result = await DialogManager(continuation_repository=repo).handle_turn(message=AgentMessage(
        id=uuid4(), project_id=uuid4(), user_id="u1",
        prompt="Crea la clase Producto y relaciona Producto con Categoria",
        status=AgentMessageStatus.RUNNING,
    ))
    assert result.status == "awaiting_input"
    assert "relaci" in result.assistant_message.lower()
    assert result.continuation is not None
    assert "Crea la clase Producto" in result.continuation.dialog_state["additional_requests"]


@pytest.mark.anyio
async def test_dialog_manager_recovery_of_completed_proposal_and_acceptance():
    """T013 / US2: Recuperación de una propuesta terminada en el historial reciente
    sin hilo abierto, y su aceptación explícita con 'implementa esos atributos'.
    Verifica también que 'sugiéreme más' conserve el estado sin mutar."""
    project_id = uuid4()
    user_id = "user_completed_proposal"

    cont_repo = InMemoryContinuationRepository()

    # Historial reciente: intercambio completado donde el asistente recomendó atributos
    completed_exchange = RecentExchange(
        message_id=uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        user_prompt="¿Qué atributos me recomiendas para Producto?",
        assistant_response=(
            "Para la clase Producto te recomiendo los siguientes atributos: "
            "`codigo` (string), `nombre` (string), `precio` (decimal) y `stock` (entero).\n\n"
            "¿Deseas que agregue estos atributos a Producto?"
        ),
        assistant_act="consult_with_proposal",
        is_superseded=False,
    )

    reader = InMemoryConversationReader([(completed_exchange, project_id, user_id)])
    dm = DialogManager(continuation_repository=cont_repo, conversation_reader=reader)

    # Caso B: "implementa esos atributos" sin hilo abierto -> recuperación exitosa de propuesta y ejecución
    msg_accept = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="implementa esos atributos",
        status=AgentMessageStatus.RUNNING,
    )
    res_accept = await dm.handle_turn(message=msg_accept)
    assert res_accept.status == "ready_to_execute"
    assert res_accept.assistant_act == "fulfill"
    assert res_accept.authorized_mode == "execute"
    assert "Producto" in res_accept.effective_request
    assert "codigo, nombre, precio, stock" in res_accept.effective_request

    msg_natural = AgentMessage(
        id=uuid4(), project_id=project_id, user_id=user_id,
        prompt="quiero que pongas todos estos atributos a esa clase",
        status=AgentMessageStatus.RUNNING,
    )
    natural = await DialogManager(
        continuation_repository=InMemoryContinuationRepository(), conversation_reader=reader,
    ).handle_turn(message=msg_natural)
    assert natural.status == "ready_to_execute"
    assert "Producto" in natural.effective_request


def test_recent_proposal_uses_persisted_structure_instead_of_markdown_parsing():
    exchange = RecentExchange(
        message_id=uuid4(), created_at=datetime.now(timezone.utc),
        user_prompt="¿Qué sugieres?", assistant_response="Recomiendo revisarlo.",
        assistant_act="consult_with_proposal",
        proposals=({
            "action": "CREATE_ATTRIBUTE",
            "slots": {"attribute.target_class": "Producto", "attribute.name": "precio, stock"},
        },),
    )
    proposals = extract_proposals_from_recent_exchanges([exchange])
    assert len(proposals) == 1
    assert proposals[0].slots["attribute.name"] == "precio, stock"


@pytest.mark.anyio
async def test_ambiguous_acceptance_can_resolve_structured_proposal_without_tools():
    provider = Mock()
    provider.complete = AsyncMock(return_value=Mock(text=json.dumps({
        "user_act": "accept_proposal", "action": "CREATE_ATTRIBUTE", "slots": {},
        "rationale": "El usuario se refiere a la propuesta pendiente.",
    })))
    state = DialogState(proposals=[Proposal(
        action="CREATE_ATTRIBUTE",
        slots={"attribute.target_class": "Producto", "attribute.name": "precio"},
    )])
    turn = await TurnInterpreter(ai_provider=provider).interpret(
        user_message="pongamos lo sugerido", dialog_state=state,
    )
    assert turn.user_act == "accept_proposal"
    assert provider.complete.await_count == 1
    assert not provider.complete.await_args.args[0].tools


@pytest.mark.anyio
async def test_dialog_manager_consultation_without_thread_is_read_only():
    """T013 / US2: 'sugiéreme más' sin hilo abierto se mantiene en modo lectura
    y no autoriza mutaciones en el diagrama."""
    project_id = uuid4()
    user_id = "user_read_only_consult"

    cont_repo = InMemoryContinuationRepository()
    reader = InMemoryConversationReader([])
    dm = DialogManager(continuation_repository=cont_repo, conversation_reader=reader)

    msg_more = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="sugiéreme más atributos para Producto",
        status=AgentMessageStatus.RUNNING,
    )
    res_more = await dm.handle_turn(message=msg_more)
    assert res_more.status == "awaiting_input"
    assert res_more.assistant_act == "consult_with_proposal"
    assert res_more.authorized_mode == "read_only"
    assert "Producto" in res_more.assistant_message


@pytest.mark.anyio
async def test_missing_consult_target_is_kept_for_a_short_followup():
    project_id = uuid4()
    repo = InMemoryContinuationRepository()
    manager = DialogManager(continuation_repository=repo)
    first = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="sugiéreme atributos", status=AgentMessageStatus.RUNNING,
    ))
    assert first.status == "awaiting_input"
    assert first.continuation is not None
    assert first.continuation.dialog_state["frames"][0]["action"] == "CONSULT_ATTRIBUTE"

    second = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="Producto", status=AgentMessageStatus.RUNNING,
    ))
    assert second.status == "awaiting_input"
    assert second.assistant_act == "consult_with_proposal"
    assert "Producto" in second.assistant_message


@pytest.mark.anyio
async def test_attribute_recommendation_reads_class_and_persists_exact_specs():
    project_id = uuid4()
    class_id = uuid4()
    query_handler = Mock()
    query_handler.search.return_value = DiagramElementSearchDto(
        items=(DiagramElementReferenceDto("class", class_id, "Producto"),),
        has_more=False, next_offset=None,
    )
    query_handler.get.return_value = DiagramElementDetailDto(
        "class", class_id, "Producto", {
            "attributes": [{"name": "nombre", "data_type": "TEXT"}],
            "attributes_truncated": False,
        },
    )
    provider = Mock()
    provider.complete = AsyncMock(return_value=Mock(text=json.dumps({"attributes": [
        {"name": "nombre", "data_type": "TEXT", "nullable": True},
        {"name": "precio", "data_type": "DECIMAL", "nullable": False},
    ]})))
    repo = InMemoryContinuationRepository()
    manager = DialogManager(
        continuation_repository=repo,
        grounded_recommendations=GroundedRecommendationService(query_handler, provider),
    )
    suggested = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="sugiéreme atributos para Producto", status=AgentMessageStatus.RUNNING,
    ))
    assert suggested.status == "awaiting_input"
    assert "precio" in suggested.assistant_message
    assert "nombre" not in suggested.assistant_message
    assert suggested.continuation.dialog_state["proposals"][0]["slots"]["attribute.specs"] == [
        {"name": "precio", "data_type": "DECIMAL", "nullable": False}
    ]
    accepted = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="sí", status=AgentMessageStatus.RUNNING,
    ))
    assert accepted.status == "ready_to_execute"
    assert "precio de tipo DECIMAL obligatorio" in accepted.effective_request


@pytest.mark.anyio
async def test_relation_recommendation_uses_both_classes_and_validates_cardinalities():
    project_id = uuid4()
    classes = {"Producto": uuid4(), "Categoria": uuid4()}
    query_handler = Mock()

    def search(query):
        name = query.query
        return DiagramElementSearchDto(
            items=(DiagramElementReferenceDto("class", classes[name], name),),
            has_more=False, next_offset=None,
        )

    def get(query):
        name = next(name for name, class_id in classes.items() if class_id == query.element_id)
        return DiagramElementDetailDto("class", query.element_id, name, {
            "attributes": [{"name": "id", "data_type": "UUID"}],
            "relations": [], "attributes_truncated": False, "relations_truncated": False,
        })

    query_handler.search.side_effect = search
    query_handler.get.side_effect = get
    provider = Mock()
    provider.complete = AsyncMock(return_value=Mock(text=json.dumps({
        "relation_type": "ASSOCIATION",
        "source_cardinality": "0..*", "target_cardinality": "1",
    })))
    repo = InMemoryContinuationRepository()
    manager = DialogManager(
        continuation_repository=repo,
        grounded_recommendations=GroundedRecommendationService(query_handler, provider),
    )
    suggested = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="¿Qué relación recomiendas entre Producto y Categoria?",
        status=AgentMessageStatus.RUNNING,
    ))
    assert suggested.status == "awaiting_input"
    assert suggested.continuation.dialog_state["proposals"][0]["slots"]["relation.source_cardinality"] == "0..*"
    accepted = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="sí", status=AgentMessageStatus.RUNNING,
    ))
    assert accepted.status == "ready_to_execute"
    assert "Producto con cardinalidad 0..*" in accepted.effective_request


@pytest.mark.anyio
async def test_dialog_manager_preserves_thread_when_asking_advice_and_alternative():
    """T013 / US2: La solicitud de consejo sobre un hilo abierto preserva el hilo
    y puede ofrecer una alternativa ante 'sugiéreme más' sin mutar."""
    project_id = uuid4()
    user_id = "user_advice_thread"

    cont_repo = InMemoryContinuationRepository()

    # Hilo activo esperando tipo de relación entre Factura y DetalleFactura
    active_state = DialogState()
    frame = DialogFrame(id="fr-fact-det", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Factura")
    frame.set_slot("relation.target_class", "DetalleFactura")
    frame.evaluate_readiness()
    active_state.add_frame(frame)

    cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request="Relaciona Factura con DetalleFactura",
        resolved_facts=[
            {"key": "relation.source_class", "value": "Factura"},
            {"key": "relation.target_class", "value": "DetalleFactura"},
        ],
        missing_fields=[{"key": "relation.type", "critical": True}],
        dialog_state=active_state.to_dict(),
    )
    cont_repo.save(cont)

    dm = DialogManager(continuation_repository=cont_repo)

    # Turno 1: "¿cuál relación tú me recomiendas?"
    msg_advice = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="¿cuál relación tú me recomiendas?",
        status=AgentMessageStatus.RUNNING,
    )
    res_advice = await dm.handle_turn(message=msg_advice)
    assert res_advice.status == "awaiting_input"
    assert res_advice.assistant_act == "consult_with_proposal"
    assert res_advice.authorized_mode == "read_only"
    # El hilo sigue abierto en AWAITING_INPUT
    saved_cont = cont_repo.find_by_id(cont.id)
    assert saved_cont.state == ContinuationState.AWAITING_INPUT
    assert "Composición" in res_advice.assistant_message

    # Turno 2: "sugiéreme más" -> alternativa (Agregación), sigue abierto
    msg_more = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="sugiéreme más",
        status=AgentMessageStatus.RUNNING,
    )
    res_more = await dm.handle_turn(message=msg_more)
    assert res_more.status == "awaiting_input"
    assert res_more.assistant_act == "consult_with_proposal"
    assert res_more.authorized_mode == "read_only"
    assert "Agregación" in res_more.assistant_message
    saved_cont2 = cont_repo.find_by_id(cont.id)
    assert saved_cont2.state == ContinuationState.AWAITING_INPUT


@pytest.mark.anyio
async def test_dialog_manager_rejects_ambiguous_or_cross_user_proposals():
    """T013 / US2: Rechazo de evidencia ambigua o ajena.
    Ante un 'sí, hazlo' sin propuesta concreta ni hilo activo, o con intercambio
    de otro usuario, pide precisión (disambiguate) sin ejecutar mutaciones ni abrir hilo."""
    project_id = uuid4()
    user_id = "user_target"
    other_user = "user_alien"

    cont_repo = InMemoryContinuationRepository()

    # Intercambio de otro usuario
    alien_exchange = RecentExchange(
        message_id=uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        user_prompt="¿Qué relación recomiendas entre Factura y Detalle?",
        assistant_response="Te recomiendo una relación de Composición entre Factura y Detalle.",
        assistant_act="consult_with_proposal",
    )

    reader = InMemoryConversationReader([(alien_exchange, project_id, other_user)])
    dm = DialogManager(continuation_repository=cont_repo, conversation_reader=reader)

    # 1. El usuario dice 'sí, hazlo', pero la propuesta es de otro usuario
    msg = AgentMessage(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="sí, hazlo",
        status=AgentMessageStatus.RUNNING,
    )
    result = await dm.handle_turn(message=msg)

    # No debe ejecutar cambios
    assert result.status == "awaiting_input"
    assert result.assistant_act == "disambiguate"
    assert "No encontré una propuesta o solicitud pendiente" in result.assistant_message
    # No debe abrir un hilo huérfano
    assert len(cont_repo.list_active_candidates(project_id=project_id, user_id=user_id)) == 0

    # 2. Con intercambio del mismo usuario pero ambiguo (sin recomendación concreta)
    ambiguous_exchange = RecentExchange(
        message_id=uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        user_prompt="¿Qué piensas del diagrama?",
        assistant_response="El diagrama tiene varias opciones y estilos posibles para explorar.",
    )

    reader2 = InMemoryConversationReader([(ambiguous_exchange, project_id, user_id)])
    dm2 = DialogManager(continuation_repository=cont_repo, conversation_reader=reader2)

    result2 = await dm2.handle_turn(message=msg)
    assert result2.status == "awaiting_input"
    assert result2.assistant_act == "disambiguate"
    assert len(cont_repo.list_active_candidates(project_id=project_id, user_id=user_id)) == 0


@pytest.mark.anyio
async def test_relation_recommendation_with_name_and_correct_cardinality():
    """Verifica que la recomendación incluya la etiqueta/verbo de relación y cardinalidades correctas."""
    project_id = uuid4()
    classes = {"Producto": uuid4(), "Categoria": uuid4()}
    query_handler = Mock()

    def search(query):
        name = query.query
        return DiagramElementSearchDto(
            items=(DiagramElementReferenceDto("class", classes[name], name),),
            has_more=False, next_offset=None,
        )

    def get(query):
        name = next(name for name, class_id in classes.items() if class_id == query.element_id)
        return DiagramElementDetailDto("class", query.element_id, name, {
            "attributes": [{"name": "id", "data_type": "UUID"}],
            "relations": [], "attributes_truncated": False, "relations_truncated": False,
        })

    query_handler.search.side_effect = search
    query_handler.get.side_effect = get
    provider = Mock()
    provider.complete = AsyncMock(return_value=Mock(text=json.dumps({
        "relation_type": "ASSOCIATION",
        "source_cardinality": "0..*",
        "target_cardinality": "1",
        "name": "pertenece",
    })))
    repo = InMemoryContinuationRepository()
    manager = DialogManager(
        continuation_repository=repo,
        grounded_recommendations=GroundedRecommendationService(query_handler, provider),
    )
    suggested = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="¿Qué relación recomiendas entre Producto y Categoria?",
        status=AgentMessageStatus.RUNNING,
    ))
    assert suggested.status == "awaiting_input"
    prop = suggested.continuation.dialog_state["proposals"][0]
    assert prop["slots"]["relation.source_cardinality"] == "0..*"
    assert prop["slots"]["relation.target_cardinality"] == "1"
    assert prop["slots"]["relation.name"] == "pertenece"
    assert "etiqueta: «pertenece»" in suggested.assistant_message

    accepted = await manager.handle_turn(message=AgentMessage(
        id=uuid4(), project_id=project_id, user_id="u1",
        prompt="sí", status=AgentMessageStatus.RUNNING,
    ))
    assert accepted.status == "ready_to_execute"
    assert 'con nombre "pertenece"' in accepted.effective_request
    assert "Producto con cardinalidad 0..*" in accepted.effective_request
    assert "Categoria con cardinalidad 1" in accepted.effective_request


@pytest.mark.anyio
async def test_turn_interpreter_extracts_relation_name_and_natural_cardinalities():
    """Verifica que el intérprete de turnos extraiga la etiqueta/nombre y cardinalidades en lenguaje natural."""
    ti = TurnInterpreter()

    # 1. Extracción de nombre/etiqueta en comando inicial
    slots = ti.relation_slots_from_request("relaciona Producto con Categoria con nombre pertenece")
    assert slots.get("relation.source_class") == "Producto"
    assert slots.get("relation.target_class") == "Categoria"
    assert slots.get("relation.name") == "pertenece"

    # 2. Extracción de cardinalidad con frase natural: "un producto tiene una categoría y una categoría tiene entre 0 a muchos productos"
    state = DialogState()
    frame = DialogFrame(id="rel1", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Producto")
    frame.set_slot("relation.target_class", "Categoria")
    frame.evaluate_readiness()
    state.add_frame(frame)

    turn = await ti.interpret(
        user_message="un producto tiene una categoría y una categoría tiene entre 0 a muchos productos",
        dialog_state=state,
    )
    assert turn.slots.get("relation.source_cardinality") == "0..*"
    assert turn.slots.get("relation.target_cardinality") == "1"

    # 3. Extracción de etiqueta en aclaración
    turn_name = await ti.interpret(
        user_message="con etiqueta pertenece",
        dialog_state=state,
    )
    assert turn_name.slots.get("relation.name") == "pertenece"



