import asyncio
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.image_storage_provider import StoredImage
from app.modules.assistant.application.use_cases.create_agent_message import (
    CreateAgentMessageCommand,
    CreateAgentMessageUseCase,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.exceptions import (
    AgentMessageAlreadyExistsException,
    AgentMessagePersistenceException,
    ImageStorageUnavailableException,
    InvalidAgentMessageException,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException


class FakeAccessPolicy:
    def __init__(self, fail_on_call: int | None = None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def ensure_read_access(self, project_id, user_id):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ProjectNotFoundException()


class FakeRepository:
    def __init__(self):
        self.messages = {}
        self.saved = []
        self.reference_result = False

    def find_by_id(self, message_id):
        return self.messages.get(message_id)

    def save_new(self, message: AgentMessage):
        self.saved.append(message)
        self.messages[message.id] = message

    def image_url_is_referenced(self, message_id, image_url):
        return self.reference_result


class FakeStorage:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []
        self.deletions = []

    async def upload(self, image_data, *, public_id):
        self.uploads.append((image_data, public_id))
        if self.fail:
            raise ImageStorageUnavailableException()
        return StoredImage(
            url="https://res.cloudinary.com/test/image/upload/example.png",
            public_id=public_id,
        )

    async def delete(self, public_id):
        self.deletions.append(public_id)


class FakeUow:
    def __init__(self, fail=False):
        self.fail = fail
        self.commits = 0

    def commit(self):
        self.commits += 1
        if self.fail:
            raise RuntimeError("commit failed")

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_text_message_does_not_require_cloudinary():
    repository, storage, uow = FakeRepository(), FakeStorage(), FakeUow()
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=uow,
    )
    result = asyncio.run(
        use_case.execute(
            CreateAgentMessageCommand(
                message_id=uuid4(),
                project_id=uuid4(),
                user_id="user-1",
                prompt="Make a class diagram",
            )
        )
    )
    assert result.image_url is None
    assert result.status == "running"
    assert storage.uploads == []
    assert uow.commits == 1


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t "])
def test_empty_prompt_is_rejected_before_upload_or_persistence(prompt):
    repository, storage, uow = FakeRepository(), FakeStorage(), FakeUow()
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=uow,
    )

    with pytest.raises(InvalidAgentMessageException):
        asyncio.run(
            use_case.execute(
                CreateAgentMessageCommand(
                    message_id=uuid4(),
                    project_id=uuid4(),
                    user_id="user-1",
                    prompt=prompt,
                    image_data=b"\x89PNG\r\n\x1a\nimage",
                    image_content_type="image/png",
                )
            )
        )

    assert storage.uploads == []
    assert repository.saved == []
    assert uow.commits == 0


def test_failed_upload_does_not_persist_message():
    repository, storage = FakeRepository(), FakeStorage(fail=True)
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=FakeUow(),
    )
    with pytest.raises(ImageStorageUnavailableException):
        asyncio.run(
            use_case.execute(
                CreateAgentMessageCommand(
                    message_id=uuid4(),
                    project_id=uuid4(),
                    user_id="user-1",
                    prompt="Make a class diagram",
                    image_data=b"\x89PNG\r\n\x1a\nimage",
                    image_content_type="image/png",
                )
            )
        )
    assert repository.saved == []


def test_known_duplicate_is_rejected_before_image_upload():
    repository, storage = FakeRepository(), FakeStorage()
    existing = AgentMessage.register(
        id=uuid4(), project_id=uuid4(), user_id="user-1", prompt="existing"
    )
    repository.messages[existing.id] = existing
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=FakeUow(),
    )
    with pytest.raises(AgentMessageAlreadyExistsException):
        asyncio.run(
            use_case.execute(
                CreateAgentMessageCommand(
                    message_id=existing.id,
                    project_id=existing.project_id,
                    user_id=existing.user_id,
                    prompt="duplicate",
                    image_data=b"\x89PNG\r\n\x1a\nimage",
                    image_content_type="image/png",
                )
            )
        )
    assert storage.uploads == []


def test_identical_retry_reuses_persisted_message_without_reuploading_image():
    repository, storage = FakeRepository(), FakeStorage()
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=FakeUow(),
    )
    command = CreateAgentMessageCommand(
        message_id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        prompt="Keep this diagram",
        image_data=b"\x89PNG\r\n\x1a\nimage",
        image_content_type="image/png",
    )

    first = asyncio.run(use_case.execute(command))
    retry = asyncio.run(use_case.execute(command))

    assert first.message_id == retry.message_id == command.message_id
    assert first.was_existing is False
    assert retry.was_existing is True
    assert len(storage.uploads) == 1


def test_permission_loss_after_upload_compensates_asset():
    repository, storage = FakeRepository(), FakeStorage()
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(fail_on_call=2),
        message_repository=repository,
        image_storage=storage,
        uow=FakeUow(),
    )
    with pytest.raises(ProjectNotFoundException):
        asyncio.run(
            use_case.execute(
                CreateAgentMessageCommand(
                    message_id=uuid4(),
                    project_id=uuid4(),
                    user_id="user-1",
                    prompt="Make a class diagram",
                    image_data=b"\x89PNG\r\n\x1a\nimage",
                    image_content_type="image/png",
                )
            )
        )
    assert len(storage.deletions) == 1
    assert repository.saved == []


def test_uncertain_commit_preserves_asset_if_reference_cannot_be_checked():
    repository, storage = FakeRepository(), FakeStorage()
    repository.reference_result = None
    use_case = CreateAgentMessageUseCase(
        project_access_policy=FakeAccessPolicy(),
        message_repository=repository,
        image_storage=storage,
        uow=FakeUow(fail=True),
    )
    with pytest.raises(AgentMessagePersistenceException):
        asyncio.run(
            use_case.execute(
                CreateAgentMessageCommand(
                    message_id=uuid4(),
                    project_id=uuid4(),
                    user_id="user-1",
                    prompt="Make a class diagram",
                    image_data=b"\x89PNG\r\n\x1a\nimage",
                    image_content_type="image/png",
                )
            )
        )
    assert storage.deletions == []
