from datetime import datetime, timezone
from uuid import uuid4

import anyio

from app.modules.assistant.application.use_cases.create_agent_message import (
    CreateAgentMessageCommand,
    CreatedAgentMessage,
)
from app.modules.assistant.application.use_cases.submit_agent_message import (
    SubmitAgentMessageUseCase,
)


def test_publishes_accepted_only_after_new_message_is_committed_and_before_dispatch():
    events = []
    message_id, project_id = uuid4(), uuid4()
    created_at = datetime.now(timezone.utc)

    class CreateMessage:
        async def execute(self, command):
            events.append("committed")
            return CreatedAgentMessage(
                message_id=message_id,
                project_id=project_id,
                status="running",
                image_url=None,
                prompt=command.prompt,
                user_id=command.user_id,
                created_at=created_at,
            )

    class AcceptancePublisher:
        async def publish_accepted(self, **payload):
            assert events == ["committed"]
            assert payload["message_id"] == message_id
            assert payload["project_id"] == project_id
            events.append("accepted")

    class Dispatcher:
        def notify(self, submitted_id):
            assert submitted_id == message_id
            events.append("dispatched")

    async def run():
        await SubmitAgentMessageUseCase(
            create_message=CreateMessage(),
            dispatcher=Dispatcher(),
            acceptance_publisher=AcceptancePublisher(),
        ).execute(
            CreateAgentMessageCommand(
                message_id=message_id,
                project_id=project_id,
                user_id="author-1",
                prompt="Create a class",
            ),
            author_name="Ada",
        )

    anyio.run(run)
    assert events == ["committed", "accepted", "dispatched"]


def test_idempotent_retry_does_not_publish_acceptance_or_dispatch_again():
    calls = []

    class CreateMessage:
        async def execute(self, _command):
            return CreatedAgentMessage(
                message_id=uuid4(),
                project_id=uuid4(),
                status="running",
                image_url=None,
                prompt="Existing",
                user_id="author-1",
                created_at=datetime.now(timezone.utc),
                was_existing=True,
            )

    class AcceptancePublisher:
        async def publish_accepted(self, **_payload):
            calls.append("accepted")

    class Dispatcher:
        def notify(self, _message_id):
            calls.append("dispatched")

    async def run():
        return await SubmitAgentMessageUseCase(
            create_message=CreateMessage(),
            dispatcher=Dispatcher(),
            acceptance_publisher=AcceptancePublisher(),
        ).execute(
            CreateAgentMessageCommand(
                message_id=uuid4(),
                project_id=uuid4(),
                user_id="author-1",
                prompt="Existing",
            )
        )

    result = anyio.run(run)
    assert result.message.was_existing is True
    assert calls == ["dispatched"]


def test_acceptance_delivery_is_best_effort_and_does_not_block_dispatch():
    calls = []

    class CreateMessage:
        async def execute(self, command):
            return CreatedAgentMessage(
                message_id=command.message_id,
                project_id=command.project_id,
                status="running",
                image_url=None,
                prompt=command.prompt,
                user_id=command.user_id,
                created_at=datetime.now(timezone.utc),
            )

    class AcceptancePublisher:
        async def publish_accepted(self, **_payload):
            raise RuntimeError("socket down")

    class Dispatcher:
        def notify(self, _message_id):
            calls.append("dispatched")

    async def run():
        await SubmitAgentMessageUseCase(
            create_message=CreateMessage(),
            dispatcher=Dispatcher(),
            acceptance_publisher=AcceptancePublisher(),
        ).execute(
            CreateAgentMessageCommand(
                message_id=uuid4(),
                project_id=uuid4(),
                user_id="author-1",
                prompt="Create a class",
            )
        )

    anyio.run(run)
    assert calls == ["dispatched"]
