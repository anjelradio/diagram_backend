"""Pruebas unitarias para el contrato del servicio ContinuationResolver."""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
    ContinuationResolution,
    ResolutionDecision,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _build_candidate(
    continuation_id: UUID | None = None,
    effective_request: str = "Relaciona Producto con Categoría",
    missing_fields: list[dict[str, Any]] | None = None,
    resolved_facts: list[dict[str, Any]] | None = None,
) -> AgentContinuation:
    cid = continuation_id or uuid4()
    return AgentContinuation(
        id=cid,
        project_id=uuid4(),
        user_id="user_1",
        root_message_id=uuid4(),
        latest_message_id=uuid4(),
        state=ContinuationState.AWAITING_INPUT,
        version=1,
        effective_request=effective_request,
        resolved_facts=resolved_facts or [],
        missing_fields=missing_fields
        or [
            {
                "key": "relation.type",
                "action": "CREATE_RELATION",
                "critical": True,
                "question": "¿Qué tipo de relación?",
            }
        ],
        outcome="awaiting_input",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )


@pytest.mark.anyio
async def test_resolver_decides_follow_up_with_valid_candidate():
    candidate = _build_candidate()
    mock_provider = AsyncMock(spec=AiProvider)
    # AI returns valid JSON matching candidate
    mock_provider.complete.return_value = AiResult(
        text=f"""{{
            "decision": "follow_up",
            "candidate_id": "{candidate.id}",
            "effective_request": "Relacionar Producto con Categoría; tipo asociación",
            "resolved_facts": [{{"key": "relation.type", "value": "ASSOCIATION"}}],
            "missing_fields": [{{"key": "relation.endpoint_cardinalities", "question": "¿Cuáles son las cardinalidades?"}}]
        }}""",
        model_role=ModelRole.MAIN,
        model="test-model",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider)
    result = await resolver.resolve(
        user_prompt="asociación",
        candidates=[candidate],
        recent_messages=[],
    )

    assert result.decision == ResolutionDecision.FOLLOW_UP
    assert result.candidate_id == candidate.id
    assert len(result.resolved_facts) == 1
    assert result.resolved_facts[0]["key"] == "relation.type"
    assert result.resolved_facts[0]["value"] == "ASSOCIATION"
    assert len(result.missing_fields) == 1


@pytest.mark.anyio
async def test_resolver_rejects_hallucinated_candidate_id_and_falls_back():
    candidate = _build_candidate()
    invented_id = uuid4()
    mock_provider = AsyncMock(spec=AiProvider)
    # AI returns an invented UUID that was not in candidates
    mock_provider.complete.return_value = AiResult(
        text=f"""{{
            "decision": "follow_up",
            "candidate_id": "{invented_id}",
            "effective_request": "Invented request",
            "resolved_facts": [],
            "missing_fields": []
        }}""",
        model_role=ModelRole.MAIN,
        model="test-model",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider)
    result = await resolver.resolve(
        user_prompt="asociación",
        candidates=[candidate],
        recent_messages=[],
    )

    # Debe rechazar el ID inventado y tratarlo como new_request sin consumir candidatos
    assert result.decision == ResolutionDecision.NEW_REQUEST
    assert result.candidate_id is None


@pytest.mark.anyio
async def test_resolver_handles_explicit_decline():
    candidate = _build_candidate()
    mock_provider = AsyncMock(spec=AiProvider)
    mock_provider.complete.return_value = AiResult(
        text=f"""{{
            "decision": "decline",
            "candidate_id": "{candidate.id}",
            "effective_request": null,
            "resolved_facts": [],
            "missing_fields": []
        }}""",
        model_role=ModelRole.MAIN,
        model="test-model",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider)
    result = await resolver.resolve(
        user_prompt="cancela eso",
        candidates=[candidate],
        recent_messages=[],
    )

    assert result.decision == ResolutionDecision.DECLINE
    assert result.candidate_id == candidate.id


@pytest.mark.anyio
async def test_resolver_handles_ambiguous_without_claim_or_exposing_uuids():
    cand1 = _build_candidate(effective_request="Crear atributo en Factura")
    cand2 = _build_candidate(effective_request="Relacionar Producto con Categoría")

    mock_provider = AsyncMock(spec=AiProvider)
    mock_provider.complete.return_value = AiResult(
        text="""{
            "decision": "ambiguous",
            "candidate_id": null,
            "effective_request": null,
            "resolved_facts": [],
            "missing_fields": [],
            "ambiguity_message": "¿Te refieres a crear el atributo en Factura o a relacionar Producto con Categoría?"
        }""",
        model_role=ModelRole.MAIN,
        model="test-model",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider)
    result = await resolver.resolve(
        user_prompt="sí, hazlo",
        candidates=[cand1, cand2],
        recent_messages=[],
    )

    assert result.decision == ResolutionDecision.AMBIGUOUS
    assert result.candidate_id is None
    # No debe exponer UUIDs en el mensaje de desambiguación
    if result.ambiguity_message:
        assert str(cand1.id) not in result.ambiguity_message
        assert str(cand2.id) not in result.ambiguity_message


@pytest.mark.anyio
async def test_resolver_fast_path_when_no_candidates():
    mock_provider = AsyncMock(spec=AiProvider)
    resolver = ContinuationResolver(ai_provider=mock_provider)

    result = await resolver.resolve(
        user_prompt="Crea una clase Cliente",
        candidates=[],
        recent_messages=[],
    )

    # Cero llamadas a AI cuando no hay candidatos abiertos
    mock_provider.complete.assert_not_called()
    assert result.decision == ResolutionDecision.NEW_REQUEST
    assert result.candidate_id is None
