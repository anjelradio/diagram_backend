from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.infrastructure.persistence.models.agent_continuation_model import (
    AgentContinuationModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def _running_message(session: Session, project: ProjectModel, user_id: str):
    message = AgentMessageModel(
        id=uuid4(),
        project_id=project.id,
        user_id=user_id,
        prompt="Cancel this request",
        status="running",
        created_date=datetime.now(timezone.utc),
    )
    session.add(message)
    session.commit()
    return message


def test_author_can_request_running_message_cancellation_idempotently(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message = _running_message(session, test_project, owner_user.user_id)
    endpoint = (
        f"/api/projects/{test_project.id}/assistant/messages/{message.id}/cancel"
    )

    first = client.post(endpoint)
    second = client.post(endpoint)

    assert first.status_code == 202
    assert first.json()["status"] == "running"
    assert first.json()["cancel_requested"] is True
    assert second.status_code == 202
    assert second.json()["cancel_requested"] is True


def test_terminal_cancel_returns_the_persisted_terminal_result(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message = AgentMessageModel(
        id=uuid4(),
        project_id=test_project.id,
        user_id=owner_user.user_id,
        prompt="Already cancelled",
        status="cancelled",
        response_markdown="La ejecución se canceló.",
    )
    session.add(message)
    session.commit()

    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages/{message.id}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["response_markdown"] == "La ejecución se canceló."


def test_member_cannot_cancel_another_authors_message(
    client: TestClient,
    session: Session,
    collaborative_project: ProjectModel,
    reader_user: AuthUser,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: reader_user
    message = _running_message(session, collaborative_project, owner_user.user_id)

    response = client.post(
        f"/api/projects/{collaborative_project.id}/assistant/messages/{message.id}/cancel"
    )

    assert response.status_code == 404


def test_cancel_closes_claimed_continuation(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message = _running_message(session, test_project, owner_user.user_id)
    cont = AgentContinuationModel(
        id=uuid4(),
        project_id=test_project.id,
        user_id=owner_user.user_id,
        root_message_id=message.id,
        latest_message_id=message.id,
        effective_request="Crea una entidad",
        purpose="clarification",
        state="claimed",
        claimed_by_message_id=message.id,
        version=1,
        expires_at=datetime.now(timezone.utc),
    )
    session.add(cont)
    session.commit()

    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages/{message.id}/cancel"
    )
    assert response.status_code == 202

    session.refresh(cont)
    assert cont.state == "declined"
    assert cont.close_reason == "cancelled"
    assert cont.claimed_by_message_id == message.id

