import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_move_diagram_class(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
    banned_user: AuthUser,
    removed_user: AuthUser,
):
    project_id = test_project.id
    class_id = str(uuid.uuid4())

    # 1. Propietario crea la clase base
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_create = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id,
            "name": "Articulo",
            "position_x": 100.0,
            "position_y": 100.0,
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
    assert resp_create.status_code == 201

    # 2. Propietario mueve la clase a nuevas coordenadas válidas -> 204 No Content
    resp_move_owner = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 550.5,
            "position_y": 620.25,
        },
    )
    assert resp_move_owner.status_code == 204

    # Verificar que las coordenadas se actualizaron en persistencia
    resp_list = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list.status_code == 200
    classes = resp_list.json()["classes"]
    updated_class = next(c for c in classes if c["id"] == class_id)
    assert updated_class["position_x"] == 550.5
    assert updated_class["position_y"] == 620.25

    # 3. Colaborador con rol EDITOR mueve la clase -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_move_editor = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 200.0,
            "position_y": 300.0,
        },
    )
    assert resp_move_editor.status_code == 204

    # 4. Colaborador con rol READER intenta mover la clase -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_move_reader = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 300.0,
            "position_y": 400.0,
        },
    )
    assert resp_move_reader.status_code == 403

    # 5. Usuario no miembro (stranger) intenta mover la clase -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_move_stranger = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 300.0,
            "position_y": 400.0,
        },
    )
    assert resp_move_stranger.status_code == 404

    # 6. Miembro removido o baneado intenta mover la clase -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    resp_move_banned = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 300.0,
            "position_y": 400.0,
        },
    )
    assert resp_move_banned.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: removed_user
    resp_move_removed = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": 300.0,
            "position_y": 400.0,
        },
    )
    assert resp_move_removed.status_code == 404

    # 7. Clase inexistente -> 404 Not Found
    app.dependency_overrides[get_current_user] = lambda: owner_user
    fake_class_id = str(uuid.uuid4())
    resp_move_not_found = client.patch(
        f"/api/diagram/classes/{fake_class_id}/position",
        json={
            "position_x": 10.0,
            "position_y": 20.0,
        },
    )
    assert resp_move_not_found.status_code == 404

    # 8. Coordenadas inválidas (no numéricas) -> 422
    resp_invalid_coords = client.patch(
        f"/api/diagram/classes/{class_id}/position",
        json={
            "position_x": "invalido",
            "position_y": 20.0,
        },
    )
    assert resp_invalid_coords.status_code == 422
