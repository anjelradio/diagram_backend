import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_delete_diagram_class(
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
    class_id_a = str(uuid.uuid4())
    class_id_b = str(uuid.uuid4())

    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Crear dos clases base
    resp_create_a = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_a,
            "name": "ClaseA",
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
    assert resp_create_a.status_code == 201

    # Crear atributo secundario en ClaseA para verificar eliminación en cascada
    attr_sec_id = str(uuid.uuid4())
    resp_attr_a = client.post(
        f"/api/diagram/classes/{class_id_a}/attributes",
        json={
            "id": attr_sec_id,
            "name": "descripcion",
            "position": 1,
        },
    )
    assert resp_attr_a.status_code == 201

    resp_create_b = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_b,
            "name": "ClaseB",
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
    assert resp_create_b.status_code == 201

    # 2. Colaborador con rol READER intenta eliminar ClaseA -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_delete_reader = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_reader.status_code == 403

    # 3. Usuario no miembro (stranger) intenta eliminar ClaseA -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_delete_stranger = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_stranger.status_code == 404

    # 4. Miembro baneado o removido intenta eliminar -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    resp_delete_banned = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_banned.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: removed_user
    resp_delete_removed = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_removed.status_code == 404

    # 5. Colaborador con rol EDITOR elimina ClaseA -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_delete_editor = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_editor.status_code == 204

    # Verificar que ClaseA fue eliminada físicamente y solo queda ClaseB
    resp_list_after_a = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list_after_a.status_code == 200
    classes_after_a = resp_list_after_a.json()["classes"]
    assert len(classes_after_a) == 1
    assert classes_after_a[0]["id"] == class_id_b

    # Verificar que los atributos de ClaseA fueron eliminados en cascada
    resp_attr_after_del = client.patch(
        f"/api/diagram/attributes/{attr_sec_id}",
        json={"name": "nuevo_nombre"},
    )
    assert resp_attr_after_del.status_code == 404

    # 6. Reintento idempotente de eliminación ya confirmada -> 204 No Content
    resp_retry_delete = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_retry_delete.status_code == 204

    # 7. Propietario elimina ClaseB (eliminación múltiple de clases desde llamadas individuales) -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_delete_b = client.delete(f"/api/diagram/classes/{class_id_b}")
    assert resp_delete_b.status_code == 204

    # Verificar que el lienzo quedó completamente vacío
    resp_list_empty = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list_empty.status_code == 200
    assert len(resp_list_empty.json()["classes"]) == 0
