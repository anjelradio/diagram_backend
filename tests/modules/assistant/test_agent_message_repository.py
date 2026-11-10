from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import (
    AgentAlreadyActiveException,
    AgentMessageAlreadyExistsException,
)
from app.modules.assistant.application.services.visual.visual_clarification import (
    create_visual_clarification,
)
from app.modules.assistant.application.services.visual.visual_contracts import VisualIntent
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def _message(project_id, message_id=None, user_id="user_owner"):
    return AgentMessage.register(
        id=message_id or uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="create",
    )


def test_second_message_is_rejected_while_author_has_active_message(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    first = _message(test_project.id)
    repository.save_new(first)
    session.commit()

    second = _message(test_project.id)
    with pytest.raises(AgentAlreadyActiveException):
        repository.save_new(second)
    session.rollback()

    assert first.status is AgentMessageStatus.RUNNING
    records = session.exec(select(AgentMessageModel)).all()
    assert [record.status for record in records].count("running") == 1
    assert len(records) == 1


def test_legacy_queued_message_is_not_claimed(
    session: Session, test_project: ProjectModel
):
    legacy = AgentMessageModel(
        id=uuid4(), project_id=test_project.id, user_id="user_owner",
        prompt="legacy", status="queued",
    )
    session.add(legacy)
    session.commit()

    claimed = SQLModelAgentMessageRepository(session).claim_next(
        worker_id="worker-a",
        now=datetime.now(timezone.utc),
        lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
    )

    assert claimed is None
    assert session.get(AgentMessageModel, legacy.id).status == "queued"


def test_claim_next_sets_lease_and_expired_lease_can_be_reclaimed(
    session: Session, test_project: ProjectModel
):
    message = _message(test_project.id)
    repository = SQLModelAgentMessageRepository(session)
    repository.save_new(message)
    session.commit()

    now = datetime.now(timezone.utc)
    claimed = repository.claim_next(
        worker_id="worker-a", now=now, lease_until=now + timedelta(seconds=30)
    )
    assert claimed is not None
    assert claimed.id == message.id
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_expires_at is not None
    session.commit()

    reclaimed_at = now + timedelta(seconds=31)
    reclaimed = repository.claim_next(
        worker_id="worker-b",
        now=reclaimed_at,
        lease_until=reclaimed_at + timedelta(seconds=30),
    )
    assert reclaimed is not None
    assert reclaimed.id == message.id
    assert reclaimed.lease_owner == "worker-b"


def test_queue_is_isolated_by_user_and_project(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    first = _message(test_project.id)
    other_user = _message(test_project.id, user_id="another-user")
    other_project = ProjectModel(
        owner_id="user_owner", name="Otro proyecto", id=uuid4()
    )
    session.add(other_project)
    session.flush()
    other_project_message = _message(other_project.id)

    repository.save_new(first)
    repository.save_new(other_user)
    repository.save_new(other_project_message)
    session.commit()

    assert {first.status, other_user.status, other_project_message.status} == {
        AgentMessageStatus.RUNNING
    }


def test_duplicate_client_uuid_is_conflict(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = _message(test_project.id)
    repository.save_new(message)
    session.commit()

    with pytest.raises(AgentMessageAlreadyExistsException):
        repository.save_new(_message(test_project.id, message.id))


def test_terminal_update_saves_response_without_changing_confirmed_image(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = AgentMessage.register(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        prompt="Review the image",
        image_url="https://res.cloudinary.com/test/image/upload/diagram.png",
    )
    repository.save_new(message)
    session.commit()

    message.complete("## Result\nLooks consistent.")
    assert repository.save_terminal(message) is True
    session.commit()

    persisted = session.get(AgentMessageModel, message.id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.response_markdown == "## Result\nLooks consistent."
    assert persisted.image_url == message.image_url


def test_plan_progress_uses_optimistic_version_and_preserves_latest_plan(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = _message(test_project.id)
    repository.save_new(message)
    session.commit()

    first_copy = repository.find_by_id(message.id)
    stale_copy = repository.find_by_id(message.id)
    assert first_copy is not None and stale_copy is not None
    first_copy.plan = {"version": 1, "status": "running"}
    assert repository.save_plan_progress(first_copy) is True
    session.commit()

    assert first_copy.plan_version == 1
    stale_copy.plan = {"version": 1, "status": "failed"}
    assert repository.save_plan_progress(stale_copy) is False
    session.rollback()

    persisted = session.get(AgentMessageModel, message.id)
    assert persisted is not None
    assert persisted.plan == {"version": 1, "status": "running"}
    assert persisted.plan_version == 1


def test_terminal_update_does_not_overwrite_a_result_already_saved(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = _message(test_project.id)
    repository.save_new(message)
    session.commit()
    first_copy = repository.find_by_id(message.id)
    stale_copy = repository.find_by_id(message.id)

    assert first_copy is not None and stale_copy is not None
    first_copy.complete("first result")
    assert repository.save_terminal(first_copy) is True
    session.commit()

    stale_copy.complete("stale result")
    assert repository.save_terminal(stale_copy) is False
    session.rollback()

    persisted = session.get(AgentMessageModel, message.id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.response_markdown == "first result"


def test_terminal_update_only_accepts_completed_or_failed_messages(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = _message(test_project.id)
    repository.save_new(message)
    session.commit()

    assert repository.save_terminal(message) is False
    session.rollback()
    assert repository.find_by_id(message.id).status is AgentMessageStatus.RUNNING


def test_visual_clarification_is_isolated_and_claimed_once(session, test_project):
    repository = SQLModelAgentMessageRepository(session)
    message = AgentMessage.register(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        prompt="Recrea Producto desde la imagen",
        image_url="https://res.cloudinary.com/test/image/upload/product.png",
    )
    intent = VisualIntent(
        mode="clarify",
        needs_image=True,
        visual_request="Producto",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "none"},
        clarification="¿Quieres incluir atributos?",
        requested_mode="mutate",
    )
    message.plan = create_visual_clarification(
        message_id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
        prompt=message.prompt,
        image_url=message.image_url,
        intent=intent,
    )
    repository.save_new(message)
    message.complete("¿Quieres incluir atributos?")
    assert repository.save_terminal(message)
    session.commit()

    pending = repository.find_pending_visual_clarifications(
        user_id="user_owner", project_id=test_project.id
    )
    assert [item.id for item in pending] == [message.id]
    assert repository.find_pending_visual_clarifications(
        user_id="another-user", project_id=test_project.id
    ) == []
    assert repository.claim_visual_clarification(
        message_id=message.id,
        expected_version=0,
        continuation_id=uuid4(),
        user_id="user_owner",
        project_id=test_project.id,
    )
    session.commit()

    assert repository.claim_visual_clarification(
        message_id=message.id,
        expected_version=0,
        continuation_id=uuid4(),
        user_id="user_owner",
        project_id=test_project.id,
    ) is False


def test_terminal_update_rejects_a_terminal_message_without_response(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentMessageRepository(session)
    message = _message(test_project.id)
    repository.save_new(message)
    session.commit()
    malformed_message = AgentMessage(
        id=message.id,
        project_id=message.project_id,
        user_id=message.user_id,
        prompt=message.prompt,
        status=AgentMessageStatus.COMPLETED,
        response_markdown=None,
    )

    assert repository.save_terminal(malformed_message) is False


def test_partial_running_index_rejects_second_active_running(
    session: Session, test_project: ProjectModel
):
    first = AgentMessageModel(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="one", status="running"
    )
    second = AgentMessageModel(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="two", status="running"
    )
    session.add(first)
    session.commit()
    session.add(second)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    invalid_status = AgentMessageModel(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="bad", status="working"
    )
    session.add(invalid_status)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
