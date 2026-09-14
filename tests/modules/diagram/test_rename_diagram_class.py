import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_rename_diagram_class(
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
    class_id_1 = str(uuid.uuid4())
    class_id_2 = str(uuid.uuid4())

    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Crear dos clases base
    resp_create_1 = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_1,
            "name": "Producto",
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
    assert resp_create_1.status_code == 201

    resp_create_2 = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_2,
            "name": "Categoria",
            "position_x": 300.0,
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
    assert resp_create_2.status_code == 201

    # 2. Propietario renombra Producto -> Articulo -> 204 No Content
    resp_rename_owner = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Articulo"},
    )
    assert resp_rename_owner.status_code == 204

    # Verificar que el nombre se actualizó
    resp_list = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list.status_code == 200
    classes = resp_list.json()["classes"]
    updated_1 = next(c for c in classes if c["id"] == class_id_1)
    assert updated_1["name"] == "Articulo"

    # 3. Renombrado idempotente con el mismo nombre -> 204 No Content
    resp_idempotent = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Articulo"},
    )
    assert resp_idempotent.status_code == 204

    # 4. Renombrar a un nombre que ya existe en el proyecto (Categoria) -> 204 No Content (permitido)
    resp_conflict = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Categoria"},
    )
    assert resp_conflict.status_code == 204

    # 5. Normalizar espacios en blanco al renombrar ("  Inventario  ") -> 204 No Content
    resp_trimmed = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "  Inventario  "},
    )
    assert resp_trimmed.status_code == 204

    resp_list_2 = client.get(f"/api/projects/{project_id}/diagram")
    classes_2 = resp_list_2.json()["classes"]
    updated_2 = next(c for c in classes_2 if c["id"] == class_id_1)
    assert updated_2["name"] == "Inventario"

    # 6. Nombre vacío o solo espacios -> 400 / 422
    resp_empty = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "   "},
    )
    assert resp_empty.status_code in (400, 422)

    # 7. Colaborador con rol EDITOR renombra -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_editor_rename = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Stock"},
    )
    assert resp_editor_rename.status_code == 204

    # 8. Colaborador con rol READER intenta renombrar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader_rename = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Almacen"},
    )
    assert resp_reader_rename.status_code == 403

    # 9. No miembro (stranger) intenta renombrar -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Almacen"},
    )
    assert resp_stranger.status_code == 404

    # 10. Miembro baneado o removido -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    resp_banned = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Almacen"},
    )
    assert resp_banned.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: removed_user
    resp_removed = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Almacen"},
    )
    assert resp_removed.status_code == 404

    # 11. Clase inexistente -> 404 Not Found
    app.dependency_overrides[get_current_user] = lambda: owner_user
    fake_id = str(uuid.uuid4())
    resp_not_found = client.patch(
        f"/api/diagram/classes/{fake_id}/name",
        json={"name": "Fantasma"},
    )
    assert resp_not_found.status_code == 404
