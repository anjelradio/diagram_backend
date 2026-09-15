import uuid
from unittest.mock import Mock
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.modules.diagram.application.services.diagram_access_policy import DiagramAccessPolicy
from app.modules.diagram.domain.exceptions import DiagramAgentLockedException
from app.modules.projects.domain.entities.project import Project
from tests.modules.diagram.conftest import create_test_attribute, create_test_class


def test_diagram_write_guard_blocks_active_agent_but_allows_internal_bypass() -> None:
    project_id = uuid.uuid4()
    project = Project(id=project_id, owner_id="owner", name="Proyecto")
    projects = Mock()
    projects.find_by_id.return_value = project
    members = Mock()
    active_reader = Mock()
    active_reader.find_active_by_project_id.return_value = object()
    policy = DiagramAccessPolicy(projects, members, active_activity_reader=active_reader)

    try:
        policy.ensure_write_access(project_id, "owner")
    except DiagramAgentLockedException:
        pass
    else:
        raise AssertionError("Una actividad activa debe bloquear mutaciones humanas")

    policy.for_agent().ensure_write_access(project_id, "owner")


def test_diagram_full_access_permissions_matrix(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    removed_user: AuthUser,
    banned_user: AuthUser,
    stranger_user: AuthUser,
):
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Setup inicial: 2 clases con PK
    c1 = create_test_class(session, project_id, name="Persona")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="Direccion")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    session.commit()

    # 1. Lectura de diagrama: OWNER, EDITOR y READER tienen 200
    for user, label in [(owner_user, "OWNER"), (editor_user, "EDITOR"), (reader_user, "READER")]:
        app.dependency_overrides[get_current_user] = lambda u=user: u
        resp = client.get(f"/api/projects/{project_id}/diagram")
        assert resp.status_code == 200, f"Fallo al leer diagrama como {label}"
        data = resp.json()
        assert len(data["classes"]) >= 2

    # Lectura rechazada para no autorizados: REMOVED, BANNED y STRANGER reciben 404 cerrado
    for user, label in [(removed_user, "REMOVED"), (banned_user, "BANNED"), (stranger_user, "STRANGER")]:
        app.dependency_overrides[get_current_user] = lambda u=user: u
        resp = client.get(f"/api/projects/{project_id}/diagram")
        assert resp.status_code == 404, f"Se esperaba 404 para {label} pero se obtuvo {resp.status_code}"

    # 2. Creación de clases: OWNER y EDITOR permitidos (201)
    app.dependency_overrides[get_current_user] = lambda: editor_user
    new_class_id = str(uuid.uuid4())
    resp_class_editor = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": new_class_id,
            "name": "Vehiculo",
            "position_x": 100.0,
            "position_y": 150.0,
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp_class_editor.status_code == 201

    # Creación de clases rechazada para READER (403)
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_class_reader = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": str(uuid.uuid4()),
            "name": "Barco",
            "position_x": 200.0,
            "position_y": 200.0,
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp_class_reader.status_code == 403

    # Creación de clases rechazada para REMOVED, BANNED y STRANGER (404)
    for user in [removed_user, banned_user, stranger_user]:
        app.dependency_overrides[get_current_user] = lambda u=user: u
        resp = client.post(
            f"/api/projects/{project_id}/diagram/classes",
            json={
                "id": str(uuid.uuid4()),
                "name": "Invalido",
                "position_x": 0.0,
                "position_y": 0.0,
                "primary_attribute": {
                    "id": str(uuid.uuid4()),
                    "name": "id",
                    "data_type": "UUID",
                    "position": 0,
                    "is_primary_key": True,
                    "is_nullable": False,
                },
            },
        )
        assert resp.status_code == 404

    # 3. Creación de relaciones: OWNER y EDITOR permitidos (201)
    rel_id = str(uuid.uuid4())
    fk_id = str(uuid.uuid4())
    relation_payload = {
        "id": rel_id,
        "name": "PersonaTieneDireccion",
        "relation_type": "ASSOCIATION",
        "source": {
            "class_id": str(c1.id),
            "handle": "RIGHT_CENTER",
            "cardinality": "1",
        },
        "target": {
            "class_id": str(c2.id),
            "handle": "LEFT_CENTER",
            "cardinality": "0..*",
        },
        "materialization": {
            "strategy": "FOREIGN_KEY",
            "foreign_attributes": [
                {
                    "id": fk_id,
                    "class_id": str(c2.id),
                    "name": "persona_id",
                    "data_type": "UUID",
                    "position": 1,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(c1.id),
                    "relation_id": rel_id,
                }
            ],
        },
    }

    # Intento de creación por READER -> 403
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_rel_reader = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=relation_payload,
    )
    assert resp_rel_reader.status_code == 403

    # Creación exitosa por EDITOR -> 201
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_rel_editor = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=relation_payload,
    )
    assert resp_rel_editor.status_code == 201

    # 4. Modificación de relación (rename)
    # READER -> 403
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_patch_reader = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "NuevoNombre"},
    )
    assert resp_patch_reader.status_code == 403

    # EDITOR -> 204
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_patch_editor = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "NuevoNombre"},
    )
    assert resp_patch_editor.status_code == 204

    # 5. Eliminación de relación
    # READER -> 403
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_del_reader = client.delete(f"/api/diagram/relations/{rel_id}")
    assert resp_del_reader.status_code == 403

    # OWNER -> 204
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_del_owner = client.delete(f"/api/diagram/relations/{rel_id}")
    assert resp_del_owner.status_code == 204
