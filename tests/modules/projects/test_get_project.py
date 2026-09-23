import uuid
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.application.queries.project.get_project import (
    GetProjectQuery,
    GetProjectQueryHandler,
)
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)


def test_get_project_query_handler_roles_and_exceptions(session: Session):
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    handler = GetProjectQueryHandler(access_policy)

    # 1. Proyecto activo
    project = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_owner",
        name="Lienzo Principal",
        description="Descripción de prueba",
        thumbnail_url="https://example.com/thumb.png",
    )
    session.add(project)
    session.flush()

    # 2. Miembros: editor, reader, removed, banned
    member_editor = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id="user_editor",
        role=ProjectMemberRole.EDITOR.value,
        status=ProjectMemberStatus.ACTIVE.value,
    )
    member_reader = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id="user_reader",
        role=ProjectMemberRole.READER.value,
        status=ProjectMemberStatus.ACTIVE.value,
    )
    member_removed = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id="user_removed",
        role=ProjectMemberRole.READER.value,
        status=ProjectMemberStatus.REMOVED.value,
    )
    member_banned = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id="user_banned",
        role=ProjectMemberRole.EDITOR.value,
        status=ProjectMemberStatus.BANNED.value,
    )
    session.add_all([member_editor, member_reader, member_removed, member_banned])
    session.commit()

    # Propietario -> OWNER
    res_owner = handler.execute(GetProjectQuery(project_id=project.id, user_id="user_owner"))
    assert res_owner.id == project.id
    assert res_owner.name == "Lienzo Principal"
    assert res_owner.description == "Descripción de prueba"
    assert res_owner.thumbnail_url == "https://example.com/thumb.png"
    assert res_owner.access_role == ProjectAccessRole.OWNER

    # Colaborador editor -> EDITOR
    res_editor = handler.execute(GetProjectQuery(project_id=project.id, user_id="user_editor"))
    assert res_editor.id == project.id
    assert res_editor.access_role == ProjectAccessRole.EDITOR

    # Colaborador lector -> READER
    res_reader = handler.execute(GetProjectQuery(project_id=project.id, user_id="user_reader"))
    assert res_reader.id == project.id
    assert res_reader.access_role == ProjectAccessRole.READER

    # No miembro (outsider) -> 404 ProjectNotFoundException
    with pytest.raises(ProjectNotFoundException):
        handler.execute(GetProjectQuery(project_id=project.id, user_id="user_stranger"))

    # Removido -> 404 ProjectNotFoundException
    with pytest.raises(ProjectNotFoundException):
        handler.execute(GetProjectQuery(project_id=project.id, user_id="user_removed"))

    # Baneado -> 404 ProjectNotFoundException
    with pytest.raises(ProjectNotFoundException):
        handler.execute(GetProjectQuery(project_id=project.id, user_id="user_banned"))

    # Proyecto inexistente -> 404 ProjectNotFoundException
    with pytest.raises(ProjectNotFoundException):
        handler.execute(GetProjectQuery(project_id=uuid.uuid4(), user_id="user_owner"))


def test_get_project_api_endpoints_permissions_matrix(client: TestClient, session: Session):
    # Crear proyecto propiedad de user_test_1
    project = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto de Arquitectura",
        description="Detalle técnico",
        thumbnail_url="https://example.com/arch.png",
    )
    session.add(project)
    session.flush()

    # user_test_2 es EDITOR
    member_editor = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id="user_test_2",
        role=ProjectMemberRole.EDITOR.value,
        status=ProjectMemberStatus.ACTIVE.value,
    )
    session.add(member_editor)
    session.commit()

    # 1. Propietario (user_test_1)
    user1 = AuthUser(user_id="user_test_1", email="uno@test.com")
    app.dependency_overrides[get_current_user] = lambda: user1

    resp_owner = client.get(f"/api/projects/{project.id}")
    assert resp_owner.status_code == 200
    data_owner = resp_owner.json()
    assert data_owner["id"] == str(project.id)
    assert data_owner["name"] == "Proyecto de Arquitectura"
    assert data_owner["description"] == "Detalle técnico"
    assert data_owner["thumbnail_url"] == "https://example.com/arch.png"
    assert data_owner["access_role"] == "OWNER"

    # 2. Editor (user_test_2)
    user2 = AuthUser(user_id="user_test_2", email="dos@test.com")
    app.dependency_overrides[get_current_user] = lambda: user2

    resp_editor = client.get(f"/api/projects/{project.id}")
    assert resp_editor.status_code == 200
    data_editor = resp_editor.json()
    assert data_editor["id"] == str(project.id)
    assert data_editor["access_role"] == "EDITOR"

    # 3. Degradar user_test_2 a READER
    member_editor.role = ProjectMemberRole.READER.value
    session.add(member_editor)
    session.commit()

    resp_reader = client.get(f"/api/projects/{project.id}")
    assert resp_reader.status_code == 200
    data_reader = resp_reader.json()
    assert data_reader["access_role"] == "READER"

    # 4. Forastero sin relación
    user3 = AuthUser(user_id="user_test_3", email="tres@test.com")
    app.dependency_overrides[get_current_user] = lambda: user3

    resp_outsider = client.get(f"/api/projects/{project.id}")
    assert resp_outsider.status_code == 404

    # 5. Usuario REMOVED
    member_editor.status = ProjectMemberStatus.REMOVED.value
    session.add(member_editor)
    session.commit()

    app.dependency_overrides[get_current_user] = lambda: user2
    resp_removed = client.get(f"/api/projects/{project.id}")
    assert resp_removed.status_code == 404

    # 6. Usuario BANNED
    member_editor.status = ProjectMemberStatus.BANNED.value
    session.add(member_editor)
    session.commit()

    resp_banned = client.get(f"/api/projects/{project.id}")
    assert resp_banned.status_code == 404

    # 7. Proyecto eliminado lógicamente (soft deleted)
    project.soft_delete()
    session.add(project)
    session.commit()

    app.dependency_overrides[get_current_user] = lambda: user1
    resp_deleted = client.get(f"/api/projects/{project.id}")
    assert resp_deleted.status_code == 404

    # 8. Proyecto inexistente
    resp_nonexistent = client.get(f"/api/projects/{uuid.uuid4()}")
    assert resp_nonexistent.status_code == 404
