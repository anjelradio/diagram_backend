from uuid import uuid4

from app.modules.assistant.application.services.context_builder import ContextBuilder
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory


class MemoryRepositoryStub:
    def __init__(self, memory=None):
        self.memory = memory
        self.lookups = []

    def find_active(self, *, user_id, project_id):
        self.lookups.append((user_id, project_id))
        return self.memory


def _message(user_id="user-a", project_id=None):
    return AgentMessage.register(
        id=uuid4(),
        project_id=project_id or uuid4(),
        user_id=user_id,
        prompt="  Summarize this project  ",
    )


def test_builds_context_without_memory():
    message = _message()
    repository = MemoryRepositoryStub()

    context = ContextBuilder(repository).build(message)

    assert context.summary_context == ""
    assert context.prompt == "Summarize this project"
    assert repository.lookups == []


def test_loads_only_the_message_users_project_memory():
    message = _message()
    memory = AgentUserMemory.create(
        user_id=message.user_id,
        project_id=message.project_id,
        summary_context="## User preferences\nUse concise explanations.",
    )
    repository = MemoryRepositoryStub(memory)

    context = ContextBuilder(repository).build(message)

    assert context.user_id == message.user_id
    assert context.project_id == message.project_id
    assert context.summary_context == ""
    assert repository.lookups == []


def test_keeps_instructions_memory_and_current_prompt_as_separate_fields():
    message = _message()
    secret_memory = "Only discuss the current user's project."
    repository = MemoryRepositoryStub(
        AgentUserMemory.create(
            user_id=message.user_id,
            project_id=message.project_id,
            summary_context=secret_memory,
        )
    )

    context = ContextBuilder(repository).build(message)

    assert secret_memory not in context.instructions
    assert message.prompt.strip() not in context.instructions
    assert context.summary_context == ""
    assert context.prompt == "Summarize this project"
    assert "no confiables" in context.instructions.lower()
