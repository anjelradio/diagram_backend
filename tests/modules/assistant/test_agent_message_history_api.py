from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


def _add_message(
    session: Session,
    project: ProjectModel,
    *,
    user_id: str,
    created_at: datetime,
    status: str = "completed",
) -> AgentMessageModel:
    message = AgentMessageModel(
        id=uuid4(),
        project_id=project.id,
        user_id=user_id,
        prompt=f"prompt {created_at.timestamp()}",
        image_url=None,
        response_markdown="respuesta persistida" if status != "running" else None,
        status=status,
        created_date=created_at,
    )
    session.add(message)
    session.flush()
    return message


def test_history_is_shared_and_paginates_against_a_fixed_snapshot(
    client: TestClient,
    session: Session,
    collaborative_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: editor_user
    owner_profile = session.get(BetterAuthUser, owner_user.user_id)
    editor_profile = session.get(BetterAuthUser, editor_user.user_id)
    assert owner_profile is not None and editor_profile is not None
    owner_profile.image = "https://cdn.example.test/owner.png"
    editor_profile.image = "https://cdn.example.test/editor.png"
    base = datetime.now(timezone.utc) - timedelta(minutes=1)
    first_page_rows = [
        _add_message(
            session,
            collaborative_project,
            user_id=owner_user.user_id if index % 2 == 0 else editor_user.user_id,
            created_at=base + timedelta(seconds=index),
        )
        for index in range(8)
    ]
    session.commit()
    snapshot_at = (base + timedelta(seconds=20)).isoformat()
    endpoint = f"/api/projects/{collaborative_project.id}/assistant/messages"

    first = client.get(endpoint, params={"limit": 6, "offset": 0, "snapshot_at": snapshot_at})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["has_more"] is True
    assert first_body["next_offset"] == 6
    assert len(first_body["items"]) == 6
    assert {item["user_id"] for item in first_body["items"]} == {
        owner_user.user_id,
        editor_user.user_id,
    }
    assert first_body["items"][0]["author_name"] in {"Owner", "Editor 1"}
    avatars = {
        item["user_id"]: item["author_avatar_url"] for item in first_body["items"]
    }
    assert avatars[owner_user.user_id] == "https://cdn.example.test/owner.png"
    assert avatars[editor_user.user_id] == "https://cdn.example.test/editor.png"

    # A newer insert must not shift the rest of this snapshot's offset pages.
    late = _add_message(
        session,
        collaborative_project,
        user_id=owner_user.user_id,
        created_at=base + timedelta(seconds=30),
    )
    session.commit()

    second = client.get(
        endpoint,
        params={"limit": 6, "offset": 6, "snapshot_at": first_body["snapshot_at"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["has_more"] is False
    assert second_body["next_offset"] is None
    assert len(second_body["items"]) == 2
    returned_ids = {
        item["message_id"]
        for item in first_body["items"] + second_body["items"]
    }
    assert returned_ids == {str(message.id) for message in first_page_rows}
    assert str(late.id) not in returned_ids


def test_active_endpoint_only_returns_the_callers_own_message(
    client: TestClient,
    session: Session,
    collaborative_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
):
    owner_profile = session.get(BetterAuthUser, owner_user.user_id)
    editor_profile = session.get(BetterAuthUser, editor_user.user_id)
    assert owner_profile is not None and editor_profile is not None
    owner_profile.image = "https://cdn.example.test/owner-avatar.png"
    editor_profile.image = "https://cdn.example.test/editor-avatar.png"
    session.commit()
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    owner_message = _add_message(
        session, collaborative_project, user_id=owner_user.user_id,
        created_at=now, status="running",
    )
    _add_message(
        session, collaborative_project, user_id=editor_user.user_id,
        created_at=now + timedelta(microseconds=1), status="running",
    )
    session.commit()
    endpoint = f"/api/projects/{collaborative_project.id}/assistant/messages/active"

    app.dependency_overrides[get_current_user] = lambda: owner_user
    owner_active = client.get(endpoint)
    assert owner_active.status_code == 200
    assert owner_active.json()["message"]["message_id"] == str(owner_message.id)
    assert owner_active.json()["message"]["author_avatar_url"] == owner_profile.image
    messages_endpoint = f"/api/projects/{collaborative_project.id}/assistant/messages"
    owner_detail = client.get(f"{messages_endpoint}/{owner_message.id}")
    assert owner_detail.status_code == 200
    assert owner_detail.json()["author_avatar_url"] == owner_profile.image

    app.dependency_overrides[get_current_user] = lambda: editor_user
    editor_active = client.get(endpoint)
    assert editor_active.status_code == 200
    assert editor_active.json()["message"]["user_id"] == editor_user.user_id
    assert editor_active.json()["message"]["author_avatar_url"] == editor_profile.image


def test_history_resolves_author_profiles_with_one_batch_query(
    client: TestClient,
    session: Session,
    collaborative_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: editor_user
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    _add_message(session, collaborative_project, user_id=owner_user.user_id, created_at=now)
    _add_message(
        session,
        collaborative_project,
        user_id=editor_user.user_id,
        created_at=now + timedelta(seconds=1),
    )
    session.commit()

    profile_queries = []
    table_name = BetterAuthUser.__tablename__

    def count_profile_queries(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.lstrip().startswith("select") and f" from {table_name.lower()} " in normalized:
            profile_queries.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", count_profile_queries)
    try:
        response = client.get(
            f"/api/projects/{collaborative_project.id}/assistant/messages",
            params={"limit": 6, "offset": 0},
        )
    finally:
        event.remove(bind, "before_cursor_execute", count_profile_queries)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert len(profile_queries) == 1


def test_history_and_detail_require_project_membership(
    client: TestClient,
    collaborative_project: ProjectModel,
    stranger_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    endpoint = f"/api/projects/{collaborative_project.id}/assistant/messages"

    assert client.get(endpoint).status_code == 404
    assert client.get(f"{endpoint}/{uuid4()}").status_code == 404


def test_history_and_active_query_handle_partial_messages(
    client: TestClient,
    session: Session,
    collaborative_project: ProjectModel,
    owner_user: AuthUser,
):
    # T009 [US1]: Mensajes con status 'partial' aparecen en el historial
    # y no son devueltos por el endpoint /active (ya que son terminales).
    app.dependency_overrides[get_current_user] = lambda: owner_user
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    partial_msg = _add_message(
        session,
        collaborative_project,
        user_id=owner_user.user_id,
        created_at=now,
        status="partial",
    )
    session.commit()

    # 1. Aparece en el historial
    response = client.get(f"/api/projects/{collaborative_project.id}/assistant/messages")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["message_id"] == str(partial_msg.id) and item["status"] == "partial" for item in items)

    # 2. No aparece en activo
    active_resp = client.get(f"/api/projects/{collaborative_project.id}/assistant/messages/active")
    assert active_resp.status_code == 200
    assert active_resp.json()["message"] is None


