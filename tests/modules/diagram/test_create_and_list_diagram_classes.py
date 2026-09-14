import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_create_and_list_diagram_classes(
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
    pk_id_1 = str(uuid.uuid4())

    # 1. Propietario crea una clase con PK cliente -> 201 Created sin cuerpo
    app.dependency_overrides[get_current_user] = lambda: owner_user
    payload_1 = {
        "id": class_id_1,
        "name": "Usuario",
        "position_x": 120.5,
        "position_y": 240.0,
        "primary_attribute": {
            "id": pk_id_1,
            "name": "id",
            "data_type": "UUID",
            "position": 0,
            "is_primary_key": True,
            "is_nullable": False,
        },
    }
    resp_create_1 = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json=payload_1,
    )
    assert resp_create_1.status_code == 201
    assert not resp_create_1.content or resp_create_1.text == ""

    # Verificar creación y PK persistida en el diagrama
    resp_diagram_1 = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_diagram_1.status_code == 200
    cls_1 = next(c for c in resp_diagram_1.json()["classes"] if c["id"] == class_id_1)
    assert cls_1["name"] == "Usuario"
    assert cls_1["position_x"] == 120.5
    assert cls_1["position_y"] == 240.0
    assert len(cls_1["attributes"]) == 1
    pk_1 = cls_1["attributes"][0]
    assert pk_1["id"] == pk_id_1
    assert pk_1["name"] == "id"
    assert pk_1["data_type"] == "UUID"
    assert pk_1["position"] == 0
    assert pk_1["is_primary_key"] is True
    assert pk_1["is_nullable"] is False

    # 2. Reintento idempotente con exactamente los mismos datos -> 204 No Content sin cuerpo
    resp_retry = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json=payload_1,
    )
    assert resp_retry.status_code == 204
    assert not resp_retry.content or resp_retry.text == ""

    # 3. Reutilizar el mismo UUID con nombre o coordenadas diferentes -> 409 Conflict
    resp_conflict_id = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_1,
            "name": "Cliente",
            "position_x": 500.0,
            "position_y": 500.0,
            "primary_attribute": {
                "id": pk_id_1,
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp_conflict_id.status_code == 409

    # 4. Crear otra clase con un nuevo UUID pero nombre duplicado -> 201 Created (permitido)
    class_id_2 = str(uuid.uuid4())
    pk_id_2 = str(uuid.uuid4())
    resp_duplicate_name = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_2,
            "name": " Usuario ",  # Se normaliza a "Usuario", permitido repetido
            "position_x": 300.0,
            "position_y": 300.0,
            "primary_attribute": {
                "id": pk_id_2,
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp_duplicate_name.status_code == 201

    # 5. Nombre vacío o de espacios en blanco -> 400 / 422 Validation Error
    resp_invalid_name = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": str(uuid.uuid4()),
            "name": "   ",
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
    assert resp_invalid_name.status_code in (400, 422)

    # 5.1 Invalid primary_attribute invariant (p.ej. name != 'id' o position != 0) -> 422
    resp_invalid_pk = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": str(uuid.uuid4()),
            "name": "Invalida",
            "position_x": 100.0,
            "position_y": 100.0,
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "custom_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp_invalid_pk.status_code == 422

    # 6. Colaborador con rol EDITOR crea una tercera clase -> 201 Created
    app.dependency_overrides[get_current_user] = lambda: editor_user
    class_id_3 = str(uuid.uuid4())
    pk_id_3 = str(uuid.uuid4())
    payload_3 = {
        "id": class_id_3,
        "name": "Pedido",
        "position_x": 350.0,
        "position_y": 180.0,
        "primary_attribute": {
            "id": pk_id_3,
            "name": "id",
            "data_type": "UUID",
            "position": 0,
            "is_primary_key": True,
            "is_nullable": False,
        },
    }
    resp_create_3 = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json=payload_3,
    )
    assert resp_create_3.status_code == 201

    # 7. Colaborador con rol READER intenta crear clase -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader_create = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": str(uuid.uuid4()),
            "name": "Factura",
            "position_x": 400.0,
            "position_y": 400.0,
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
    assert resp_reader_create.status_code == 403

    # 8. Colaborador con rol READER obtiene el diagrama -> 200 OK sin can_edit
    resp_reader_diagram = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_reader_diagram.status_code == 200
    reader_data = resp_reader_diagram.json()
    assert "can_edit" not in reader_data
    assert len(reader_data["classes"]) == 3
    for c in reader_data["classes"]:
        assert "attributes" in c
        assert len(c["attributes"]) >= 1

    # 9. Propietario obtiene el diagrama -> 200 OK sin can_edit
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_owner_diagram = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_owner_diagram.status_code == 200
    owner_data = resp_owner_diagram.json()
    assert "can_edit" not in owner_data
    assert len(owner_data["classes"]) == 3

    # 10. Extraño / no miembro intenta listar o crear -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger_list = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_stranger_list.status_code == 404

    # 11. Miembro baneado o removido intenta acceder -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    resp_banned_list = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_banned_list.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: removed_user
    resp_removed_list = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_removed_list.status_code == 404
