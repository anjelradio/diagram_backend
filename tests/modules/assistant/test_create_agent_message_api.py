from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)


class FakeCloudinaryProvider:
    async def upload(self, image_data: bytes, *, public_id: str):
        from app.modules.assistant.application.ports.providers.image_storage_provider import (
            StoredImage,
        )

        return StoredImage(
            url="https://res.cloudinary.com/test/image/upload/diagram.png",
            public_id=public_id,
        )

    async def delete(self, public_id: str) -> None:
        pass


def test_create_message_returns_accepted_persisted_projection_and_dispatches(
    client: TestClient, test_project: ProjectModel, owner_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message_id = uuid4()
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(message_id)),
            "prompt": (None, "  Describe this ERD  "),
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "message_id": str(message_id),
        "project_id": str(test_project.id),
        "status": "running",
        "image_url": None,
        "prompt": "Describe this ERD",
        "user_id": owner_user.user_id,
        "author_name": "Propietario",
        "author_avatar_url": None,
        "cancel_requested": False,
        "created_at": response.json()["created_at"],
        "response_markdown": None,
    }
    assert app.state.agent_job_runner.notifications == [message_id]


def test_api_broadcasts_only_new_persisted_acceptance_before_retry(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    from app.modules.assistant.infrastructure.api.routers import assistant_router
    from app.shared.infrastructure.db.better_auth import BetterAuthUser

    published = []
    profile = session.get(BetterAuthUser, owner_user.user_id)
    assert profile is not None
    profile.image = "https://cdn.example.test/ada.png"
    session.commit()

    class FakeAcceptancePublisher:
        async def publish_accepted(self, **event):
            assert session.get(AgentMessageModel, event["message_id"]) is not None
            published.append(event)

    monkeypatch.setattr(
        assistant_router, "WebSocketAgentAcceptancePublisher", FakeAcceptancePublisher
    )
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message_id = uuid4()
    endpoint = f"/api/projects/{test_project.id}/assistant/messages"
    form = {
        "message_id": (None, str(message_id)),
        "prompt": (None, "Create Product"),
    }

    assert client.post(endpoint, files=form).status_code == 202
    assert client.post(endpoint, files=form).status_code == 200
    assert len(published) == 1
    assert published[0]["message_id"] == message_id
    assert published[0]["project_id"] == test_project.id
    assert published[0]["author_name"] == "Propietario"
    assert published[0]["author_avatar_url"] == "https://cdn.example.test/ada.png"


def test_old_assistant_routes_and_history_alias_are_removed(client: TestClient):
    assert client.post("/api/assistant/voice").status_code == 404
    assert client.post("/api/assistant/image").status_code == 404
    assert client.get(f"/api/projects/{uuid4()}/assistant/activities").status_code == 404


def test_rejects_unknown_form_fields_before_upload(
    client: TestClient, test_project: ProjectModel, owner_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Create a model"),
            "user_id": (None, "forged-user"),
        },
    )
    assert response.status_code == 422


def test_reader_can_create_message_without_mutating_diagram(
    client: TestClient, test_project: ProjectModel, reader_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: reader_user
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Analyze this project"),
        },
    )
    assert response.status_code == 202


def test_image_is_uploaded_returned_and_persisted(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    from app.modules.assistant.infrastructure.api.routers import assistant_router

    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(
        assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider
    )
    message_id = uuid4()
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(message_id)),
            "prompt": (None, "Review this image"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )
    assert response.status_code == 202
    assert response.json()["image_url"] == (
        "https://res.cloudinary.com/test/image/upload/diagram.png"
    )
    record = session.get(AgentMessageModel, message_id)
    assert record is not None
    assert record.image_url == response.json()["image_url"]


def test_blank_prompt_with_image_is_rejected_before_cloudinary_upload(
    monkeypatch,
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    from app.modules.assistant.infrastructure.api.routers import assistant_router

    calls = []

    class CountingCloudinaryProvider:
        async def upload(self, _image_data: bytes, *, public_id: str):
            calls.append(public_id)
            raise AssertionError("no debe subirse una imagen sin prompt")

        async def delete(self, _public_id: str) -> None:
            pass

    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(
        assistant_router, "CloudinaryImageProvider", CountingCloudinaryProvider
    )
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "   "),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    assert response.status_code == 422
    assert calls == []


def test_missing_authentication_is_rejected(client: TestClient, test_project: ProjectModel):
    app.dependency_overrides.pop(get_current_user, None)
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={"message_id": (None, str(uuid4())), "prompt": (None, "Create a model")},
    )
    assert response.status_code == 401


def test_oversized_image_is_rejected(client: TestClient, test_project: ProjectModel, owner_user):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Review image"),
            "image": ("large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png"),
        },
    )
    assert response.status_code == 413


def test_duplicate_message_id_returns_conflict(
    client: TestClient, test_project: ProjectModel, owner_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    message_id = str(uuid4())
    endpoint = f"/api/projects/{test_project.id}/assistant/messages"
    form = {"message_id": (None, message_id), "prompt": (None, "Create a model")}
    assert client.post(endpoint, files=form).status_code == 202
    assert client.post(endpoint, files=form).status_code == 200


def test_same_message_id_with_different_payload_conflicts(
    client: TestClient, test_project: ProjectModel, owner_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    endpoint = f"/api/projects/{test_project.id}/assistant/messages"
    message_id = str(uuid4())
    first = client.post(
        endpoint,
        files={"message_id": (None, message_id), "prompt": (None, "First prompt")},
    )
    second = client.post(
        endpoint,
        files={"message_id": (None, message_id), "prompt": (None, "Different prompt")},
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "MESSAGE_ID_CONFLICT"


def test_second_distinct_active_message_is_rejected(
    client: TestClient, test_project: ProjectModel, owner_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    endpoint = f"/api/projects/{test_project.id}/assistant/messages"
    first = client.post(
        endpoint,
        files={"message_id": (None, str(uuid4())), "prompt": (None, "First prompt")},
    )
    second = client.post(
        endpoint,
        files={"message_id": (None, str(uuid4())), "prompt": (None, "Second prompt")},
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ACTIVE_MESSAGE_EXISTS"


def test_rejects_user_without_project_access(
    client: TestClient, test_project: ProjectModel, stranger_user: AuthUser
):
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    response = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Analyze this project"),
        },
    )
    assert response.status_code == 404
