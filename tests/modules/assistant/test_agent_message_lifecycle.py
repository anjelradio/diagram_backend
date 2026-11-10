from uuid import uuid4

import pytest

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import InvalidAgentMessageException


def _message(status: AgentMessageStatus = AgentMessageStatus.RUNNING) -> AgentMessage:
    return AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="Describe the project",
        status=status,
    )


def test_running_message_can_complete_with_non_empty_markdown_and_no_plan():
    message = _message()

    message.complete("## Summary\nA useful response.")

    assert message.status is AgentMessageStatus.COMPLETED
    assert message.response_markdown == "## Summary\nA useful response."
    assert message.plan is None


def test_running_message_can_fail_without_saving_response():
    message = _message()

    message.fail()

    assert message.status is AgentMessageStatus.FAILED
    assert message.response_markdown == "No pude completar la solicitud. Inténtalo de nuevo."


@pytest.mark.parametrize(
    "status",
    [AgentMessageStatus.QUEUED, AgentMessageStatus.COMPLETED, AgentMessageStatus.FAILED, AgentMessageStatus.CANCELLED],
)
def test_only_running_message_can_complete_or_fail(status):
    message = _message(status)

    with pytest.raises(InvalidAgentMessageException):
        message.complete("answer")
    with pytest.raises(InvalidAgentMessageException):
        message.fail()


@pytest.mark.parametrize("response", ["", "  ", None])
def test_completion_requires_a_non_empty_response(response):
    message = _message()

    with pytest.raises(InvalidAgentMessageException):
        message.complete(response)
