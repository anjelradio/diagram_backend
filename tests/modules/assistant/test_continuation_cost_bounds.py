"""Pruebas de límites de costo e inferencia para continuidad conversacional (T046)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
    ResolutionDecision,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _make_candidate(req_name: str) -> AgentContinuation:
    return AgentContinuation(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_cost",
        root_message_id=uuid4(),
        latest_message_id=uuid4(),
        state=ContinuationState.AWAITING_INPUT,
        version=1,
        effective_request=req_name,
        resolved_facts=[],
        missing_fields=[{"key": "test.field", "critical": True}],
        outcome="awaiting_input",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )


@pytest.mark.anyio
async def test_zero_additional_inferences_for_simple_request_without_pending():
    """Una solicitud simple cuando no hay candidatos pendientes produce cero llamadas a la IA."""
    mock_provider = AsyncMock(spec=AiProvider)
    resolver = ContinuationResolver(ai_provider=mock_provider)

    resolution = await resolver.resolve(
        user_prompt="Crea una clase Producto",
        candidates=[],
        recent_messages=[],
    )

    # Cero inferencias en el proveedor AI
    mock_provider.complete.assert_not_called()
    assert resolution.decision == ResolutionDecision.NEW_REQUEST
    assert resolution.candidate_id is None
    assert resolution.effective_request == "Crea una clase Producto"


@pytest.mark.anyio
async def test_candidate_list_clamped_to_maximum_of_three():
    """El resolver acota estrictamente la evaluación a como máximo 3 candidatos."""
    candidates = [_make_candidate(f"Petición {i}") for i in range(10)]

    mock_provider = AsyncMock(spec=AiProvider)
    mock_provider.complete.return_value = AiResult(
        text=f"""{{
            "decision": "follow_up",
            "candidate_id": "{candidates[0].id}",
            "effective_request": "Petición 0",
            "resolved_facts": [],
            "missing_fields": []
        }}""",
        model_role=ModelRole.MAIN,
        model="test-bounds",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider, max_candidates=3)
    await resolver.resolve(
        user_prompt="sí",
        candidates=candidates,
        recent_messages=[],
    )

    # Verificar payload enviado a la IA
    assert mock_provider.complete.call_count == 1
    call_args = mock_provider.complete.call_args[0][0]
    user_msg_content = call_args.messages[1].content
    payload = json.loads(user_msg_content)

    assert len(payload["pending_candidates"]) == 3
    sent_ids = {c["id"] for c in payload["pending_candidates"]}
    assert sent_ids == {str(candidates[0].id), str(candidates[1].id), str(candidates[2].id)}


@pytest.mark.anyio
async def test_recent_conversation_turns_clamped_to_maximum_of_six():
    """El historial conversacional adjunto al prompt de resolución no excede 6 turnos."""
    candidate = _make_candidate("Petición única")
    recent_turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Turno {i}"} for i in range(20)]

    mock_provider = AsyncMock(spec=AiProvider)
    mock_provider.complete.return_value = AiResult(
        text=f"""{{
            "decision": "follow_up",
            "candidate_id": "{candidate.id}",
            "effective_request": "Petición única",
            "resolved_facts": [],
            "missing_fields": []
        }}""",
        model_role=ModelRole.MAIN,
        model="test-bounds",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider, max_evidence_turns=6)
    await resolver.resolve(
        user_prompt="continuar",
        candidates=[candidate],
        recent_messages=recent_turns,
    )

    assert mock_provider.complete.call_count == 1
    call_args = mock_provider.complete.call_args[0][0]
    user_msg_content = call_args.messages[1].content
    payload = json.loads(user_msg_content)

    assert len(payload["recent_conversation_turns"]) == 6
    assert payload["recent_conversation_turns"][0]["content"] == "Turno 0"
    assert payload["recent_conversation_turns"][5]["content"] == "Turno 5"


@pytest.mark.anyio
async def test_self_sufficient_request_in_dialog_manager_has_zero_history_reads_and_zero_inferences():
    """Una orden autónoma evaluada por DialogManager no lee el historial ni hace inferencias de análisis."""
    from unittest.mock import MagicMock
    from app.modules.assistant.application.services.dialog.dialog_manager import DialogManager
    from app.modules.assistant.domain.entities.agent_message import AgentMessage
    from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
        AgentConversationReader,
    )

    mock_provider = AsyncMock(spec=AiProvider)
    mock_reader = MagicMock(spec=AgentConversationReader)
    mock_repo = MagicMock()
    mock_repo.list_active_candidates.return_value = []
    mock_repo.find_active_by_scope.return_value = None

    dialog_manager = DialogManager(
        continuation_repository=mock_repo,
        conversation_reader=mock_reader,
        ai_provider=mock_provider,
    )

    msg = AgentMessage.register(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_cost",
        prompt="Crea la clase Factura con el atributo total",
    )

    result = await dialog_manager.handle_turn(message=msg, summary_context="")

    # Verificaciones de límites de costo:
    assert result.status == "pass_through"
    assert result.effective_request == "Crea la clase Factura con el atributo total"
    assert mock_reader.get_recent_exchanges.call_count == 0  # Cero lecturas de historial
    assert mock_provider.complete.call_count == 0  # Cero inferencias adicionales a la IA
