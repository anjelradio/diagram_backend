from uuid import uuid4

from app.modules.assistant.application.services.context_builder import ContextBuilder
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory


class PairMemoryRepository:
    def __init__(self, memories):
        self.memories = memories
        self.lookups = []

    def find_active(self, *, user_id, project_id):
        self.lookups.append((user_id, project_id))
        return self.memories.get((user_id, project_id))


def _message(user_id, project_id):
    return AgentMessage.register(
        id=uuid4(), project_id=project_id, user_id=user_id, prompt="Summarize"
    )


def test_context_builder_never_includes_memory_from_other_users_or_projects():
    project_a = uuid4()
    project_b = uuid4()
    memories = {
        ("user-a", project_a): AgentUserMemory.create(
            user_id="user-a", project_id=project_a, summary_context="PRIVATE A"
        ),
        ("user-b", project_a): AgentUserMemory.create(
            user_id="user-b", project_id=project_a, summary_context="PRIVATE B"
        ),
        ("user-a", project_b): AgentUserMemory.create(
            user_id="user-a", project_id=project_b, summary_context="PRIVATE OTHER PROJECT"
        ),
    }
    repository = PairMemoryRepository(memories)
    builder = ContextBuilder(repository)

    own_context = builder.build(_message("user-a", project_a))
    missing_context = builder.build(_message("user-c", project_a))

    assert own_context.summary_context == ""
    assert "PRIVATE B" not in own_context.summary_context
    assert "PRIVATE OTHER PROJECT" not in own_context.summary_context
    assert missing_context.summary_context == ""
    assert repository.lookups == []
