from uuid import uuid4

import pytest

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import InvalidAgentMessageException


def test_message_keeps_client_identity_and_nullable_future_fields():
    message_id = uuid4()
    message = AgentMessage.register(
        id=message_id,
        project_id=uuid4(),
        user_id="user-1",
        prompt="  Build a diagram  ",
    )

    assert message.id == message_id
    assert message.prompt == "Build a diagram"
    assert message.status is AgentMessageStatus.RUNNING
    assert message.image_url is None
    assert message.response_markdown is None
    assert message.plan is None


@pytest.mark.parametrize(
    "value", ["", "   ", "x" * 10_001]
)
def test_message_rejects_empty_or_too_long_prompt(value: str):
    with pytest.raises(InvalidAgentMessageException):
        AgentMessage.register(
            id=uuid4(), project_id=uuid4(), user_id="user-1", prompt=value
        )


def test_queued_status_has_no_implicit_transition():
    message = AgentMessage.register(
        id=uuid4(), project_id=uuid4(), user_id="user-1", prompt="hello"
    )
    message.queue()
    assert message.status is AgentMessageStatus.QUEUED
    assert {status.value for status in AgentMessageStatus} == {
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "cancelled",
    }


def test_partial_transition_succeeds_for_running_message():
    message = AgentMessage.register(
        id=uuid4(), project_id=uuid4(), user_id="user-1", prompt="hello"
    )
    message.partial("Se completó 1 tarea y 1 quedó pendiente.")
    assert message.status is AgentMessageStatus.PARTIAL
    assert message.response_markdown == "Se completó 1 tarea y 1 quedó pendiente."


def test_partial_transition_rejects_empty_response():
    message = AgentMessage.register(
        id=uuid4(), project_id=uuid4(), user_id="user-1", prompt="hello"
    )
    with pytest.raises(InvalidAgentMessageException):
        message.partial("   ")


def test_partial_transition_fails_if_message_is_not_running():
    message = AgentMessage.register(
        id=uuid4(), project_id=uuid4(), user_id="user-1", prompt="hello"
    )
    message.queue()
    with pytest.raises(InvalidAgentMessageException):
        message.partial("Resultado parcial")

