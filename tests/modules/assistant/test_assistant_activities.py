import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_activity_state import AgentActivityState
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
    SQLModelAgentActivityRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_list_activities_empty(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user
    response = client.get(f"/api/projects/{test_project.id}/assistant/activities")
    assert response.status_code == 200
    assert response.json() == []


def test_list_activities_with_records(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user
    repo = SQLModelAgentActivityRepository(session)

    act1 = AgentActivity(
        id=uuid.uuid4(),
        project_id=test_project.id,
        transcription="Crear clase Usuario",
        resume="Se creo la clase Usuario",
        image_url=None,
        state=AgentActivityState.FINISHED,
    )
    repo.save(act1)
    session.commit()

    act2 = AgentActivity(
        id=uuid.uuid4(),
        project_id=test_project.id,
        transcription="Crear clase Pedido",
        resume="Se creo la clase Pedido",
        image_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
        state=AgentActivityState.FINISHED,
    )
    repo.save(act2)
    session.commit()

    response = client.get(f"/api/assistant/projects/{test_project.id}/activities")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    # Verifica exclusión estricta de modified_date y deleted_date
    for item in data:
        assert "modified_date" not in item
        assert "deleted_date" not in item
        assert "id" in item
        assert "project_id" in item
        assert "transcription" in item
        assert "resume" in item
        assert "state" in item
        assert "created_date" in item

    # Verifica alias bajo /api/projects/{id}/assistant/activities
    alias_res = client.get(f"/api/projects/{test_project.id}/assistant/activities")
    assert alias_res.status_code == 200
    assert len(alias_res.json()) == 2


def test_list_activities_reader_allowed(
    client: TestClient,
    test_project: ProjectModel,
    reader_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: reader_user
    response = client.get(f"/api/assistant/projects/{test_project.id}/activities")
    assert response.status_code == 200


def test_list_activities_stranger_forbidden(
    client: TestClient,
    test_project: ProjectModel,
    stranger_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    response = client.get(f"/api/assistant/projects/{test_project.id}/activities")
    # closed failure per policy: returns 404
    assert response.status_code == 404


def test_list_activities_unauthenticated(
    client: TestClient,
    test_project: ProjectModel,
) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    response = client.get(f"/api/assistant/projects/{test_project.id}/activities")
    assert response.status_code == 401


def test_activity_repository_finds_only_active_activity_per_project(
    session: Session,
    test_project: ProjectModel,
) -> None:
    repo = SQLModelAgentActivityRepository(session)
    active = AgentActivity(
        id=uuid.uuid4(),
        project_id=test_project.id,
        state=AgentActivityState.IN_PROGRESS,
    )
    finished = AgentActivity(
        id=uuid.uuid4(),
        project_id=test_project.id,
        state=AgentActivityState.FINISHED,
    )
    repo.save(active)
    repo.save(finished)
    session.commit()

    found = repo.find_active_by_project_id(test_project.id)
    assert found is not None
    assert found.id == active.id

    # Cuando la actividad pasa a FINISHED, ya no se considera activa
    active.finish(
        transcription="Crear clase Usuario",
        resume="Completado exitosamente",
    )
    repo.save(active)
    session.commit()

    assert repo.find_active_by_project_id(test_project.id) is None


def test_list_activities_editor_allowed(
    client: TestClient,
    test_project: ProjectModel,
    editor_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: editor_user
    response = client.get(f"/api/assistant/projects/{test_project.id}/activities")
    assert response.status_code == 200


def test_list_activities_owner_editor_reader_all_authorized(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
) -> None:
    for user in [owner_user, editor_user, reader_user]:
        app.dependency_overrides[get_current_user] = lambda u=user: u
        response = client.get(f"/api/projects/{test_project.id}/assistant/activities")
        assert response.status_code == 200
