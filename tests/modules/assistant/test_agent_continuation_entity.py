"""Pruebas unitarias para la entidad de dominio AgentContinuation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
    ContinuationOutcome,
)
from app.modules.assistant.domain.exceptions import DomainException


def test_agent_continuation_named_constructor_creates_valid_instance():
    continuation_id = uuid4()
    project_id = uuid4()
    user_id = "user_123"
    root_message_id = uuid4()

    continuation = AgentContinuation.create(
        id=continuation_id,
        project_id=project_id,
        user_id=user_id,
        root_message_id=root_message_id,
        effective_request="Relaciona Producto con Categoría",
        missing_fields=[
            {"key": "relation.type", "question": "¿Qué tipo de relación?", "critical": True}
        ],
    )

    assert continuation.id == continuation_id
    assert continuation.project_id == project_id
    assert continuation.user_id == user_id
    assert continuation.root_message_id == root_message_id
    assert continuation.latest_message_id == root_message_id
    assert continuation.state == ContinuationState.AWAITING_INPUT
    assert continuation.version == 1
    assert continuation.effective_request == "Relaciona Producto con Categoría"
    assert len(continuation.missing_fields) == 1
    assert len(continuation.resolved_facts) == 0
    assert continuation.outcome == ContinuationOutcome.AWAITING_INPUT
    assert continuation.claimed_by_message_id is None
    assert continuation.expires_at > datetime.now(timezone.utc) + timedelta(hours=23)


def test_agent_continuation_limits_enforcement():
    project_id = uuid4()
    user_id = "user_123"
    root_msg_id = uuid4()

    # Más de 20 hechos debe fallar o acotarse con excepción de dominio
    too_many_facts = [{"key": f"k_{i}", "value": f"v_{i}"} for i in range(25)]
    with pytest.raises(DomainException):
        AgentContinuation.create(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            root_message_id=root_msg_id,
            effective_request="Test",
            resolved_facts=too_many_facts,
        )

    # Más de 20 campos faltantes debe fallar
    too_many_questions = [{"key": f"q_{i}", "question": f"text_{i}"} for i in range(25)]
    with pytest.raises(DomainException):
        AgentContinuation.create(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            root_message_id=root_msg_id,
            effective_request="Test",
            missing_fields=too_many_questions,
        )

    # Más de 10 referencias de mensajes recientes debe fallar
    too_many_messages = [uuid4() for _ in range(15)]
    with pytest.raises(DomainException):
        AgentContinuation.create(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            root_message_id=root_msg_id,
            effective_request="Test",
            recent_message_ids=too_many_messages,
        )


def test_agent_continuation_claim_optimistic_concurrency_and_transition():
    c = AgentContinuation.create(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_123",
        root_message_id=uuid4(),
        effective_request="Test request",
    )
    assert c.version == 1

    consumer_msg_id = uuid4()
    # Claim con versión esperada correcta
    claimed = c.claim(by_message_id=consumer_msg_id, expected_version=1)
    assert claimed.state == ContinuationState.CLAIMED
    assert claimed.claimed_by_message_id == consumer_msg_id
    assert claimed.version == 2

    # Intentar reclamar de nuevo con versión vieja debe fallar
    with pytest.raises(DomainException):
        claimed.claim(by_message_id=uuid4(), expected_version=1)

    # Intentar reclamar una ya reclamada debe fallar
    with pytest.raises(DomainException):
        claimed.claim(by_message_id=uuid4(), expected_version=2)


def test_agent_continuation_transitions_to_ready_resolved_declined():
    c = AgentContinuation.create(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_123",
        root_message_id=uuid4(),
        effective_request="Relaciona",
        missing_fields=[{"key": "type", "question": "¿Tipo?", "critical": True}],
    )
    assert c.state == ContinuationState.AWAITING_INPUT

    # Responder aclaración completando todos los datos faltantes -> pasa a READY
    new_msg_id = uuid4()
    ready = c.apply_clarification(
        new_effective_request="Relaciona Producto con Categoría mediante asociación",
        resolved_facts=[{"key": "type", "value": "ASSOCIATION", "provenance": "msg_2"}],
        remaining_missing_fields=[],
        latest_message_id=new_msg_id,
    )
    assert ready.state == ContinuationState.READY
    assert ready.latest_message_id == new_msg_id
    assert ready.version == 2
    assert len(ready.missing_fields) == 0
    assert len(ready.resolved_facts) == 1

    # Reclamar y luego resolver
    consumer_id = uuid4()
    claimed = ready.claim(by_message_id=consumer_id, expected_version=2)
    resolved = claimed.resolve(outcome=ContinuationOutcome.SUCCESS)
    assert resolved.state == ContinuationState.RESOLVED
    assert resolved.outcome == ContinuationOutcome.SUCCESS
    assert resolved.version == 4

    # Rechazo (decline)
    c2 = AgentContinuation.create(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_123",
        root_message_id=uuid4(),
        effective_request="Otra",
    )
    declined = c2.decline()
    assert declined.state == ContinuationState.DECLINED
    assert declined.version == 2


def test_agent_continuation_expiration_check():
    now = datetime.now(timezone.utc)
    c = AgentContinuation.create(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user_123",
        root_message_id=uuid4(),
        effective_request="Expirable",
    )
    assert c.is_expired(now=now) is False
    assert c.is_expired(now=now + timedelta(hours=25)) is True
