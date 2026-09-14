import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_reposition_diagram_attribute(
    client: TestClient,
    test_project: ProjectModel,
    test_class_with_attributes: DiagramClassModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Snapshot inicial
    resp_diagram = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp_diagram.status_code == 200
    cls_data = next(
        c for c in resp_diagram.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    pk_attr = next(a for a in cls_data["attributes"] if a["is_primary_key"])
    sec_1 = next(a for a in cls_data["attributes"] if a["name"] == "nombre")
    sec_2 = next(a for a in cls_data["attributes"] if a["name"] == "edad")
    sec_3 = next(a for a in cls_data["attributes"] if a["name"] == "activo")

    pk_id = pk_attr["id"]
    sec_1_id = sec_1["id"]
    sec_2_id = sec_2["id"]
    sec_3_id = sec_3["id"]

    # Verificar posiciones iniciales: PK=0, sec_1=1, sec_2=2, sec_3=3
    assert pk_attr["position"] == 0
    assert sec_1["position"] == 1
    assert sec_2["position"] == 2
    assert sec_3["position"] == 3

    # 1. Mover el tercer atributo hacia arriba a posición 1 -> 204 No Content
    resp_move_1 = client.patch(
        f"/api/diagram/attributes/{sec_3_id}/position",
        json={"position": 1},
    )
    assert resp_move_1.status_code == 204

    # Recargar snapshot y comprobar secuencia contigua:
    # PK=0, sec_3=1, sec_1=2, sec_2=3
    resp_snap_1 = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_snap_1 = next(
        c for c in resp_snap_1.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    positions_1 = {a["id"]: a["position"] for a in cls_snap_1["attributes"]}
    assert positions_1[pk_id] == 0
    assert positions_1[sec_3_id] == 1
    assert positions_1[sec_1_id] == 2
    assert positions_1[sec_2_id] == 3

    # 2. Mover sec_3 hacia el final a posición 3 -> 204 No Content
    resp_move_2 = client.patch(
        f"/api/diagram/attributes/{sec_3_id}/position",
        json={"position": 3},
    )
    assert resp_move_2.status_code == 204

    # Recargar snapshot: PK=0, sec_1=1, sec_2=2, sec_3=3
    resp_snap_2 = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_snap_2 = next(
        c for c in resp_snap_2.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    positions_2 = {a["id"]: a["position"] for a in cls_snap_2["attributes"]}
    assert positions_2[pk_id] == 0
    assert positions_2[sec_1_id] == 1
    assert positions_2[sec_2_id] == 2
    assert positions_2[sec_3_id] == 3

    # 3. Mover a la misma posición actual (idempotente/sin cambios) -> 204 No Content
    resp_move_same = client.patch(
        f"/api/diagram/attributes/{sec_2_id}/position",
        json={"position": 2},
    )
    assert resp_move_same.status_code == 204

    # 4. Proteger PK: Intentar reposicionar la llave primaria -> 409 Conflict
    resp_move_pk = client.patch(
        f"/api/diagram/attributes/{pk_id}/position",
        json={"position": 1},
    )
    assert resp_move_pk.status_code == 409
    assert resp_move_pk.json()["error"]["code"] == "PRIMARY_KEY_CANNOT_BE_REPOSITIONED"

    # 5. Intentar asignar posición 0 -> 422 (Pydantic ge=1)
    resp_pos_0 = client.patch(
        f"/api/diagram/attributes/{sec_1_id}/position",
        json={"position": 0},
    )
    assert resp_pos_0.status_code == 422

    # 6. Intentar asignar posición fuera del rango de secundarios (por ejemplo 10) -> 400 Bad Request
    resp_pos_out_of_bounds = client.patch(
        f"/api/diagram/attributes/{sec_1_id}/position",
        json={"position": 10},
    )
    assert resp_pos_out_of_bounds.status_code == 400
    assert resp_pos_out_of_bounds.json()["error"]["code"] == "INVALID_ATTRIBUTE_POSITION"

    # 7. Payload con campos adicionales -> 422 (extra="forbid")
    resp_extra_field = client.patch(
        f"/api/diagram/attributes/{sec_1_id}/position",
        json={"position": 2, "name": "nuevo"},
    )
    assert resp_extra_field.status_code == 422

    # 8. Colaborador con rol EDITOR reposiciona -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_editor = client.patch(
        f"/api/diagram/attributes/{sec_2_id}/position",
        json={"position": 1},
    )
    assert resp_editor.status_code == 204

    # 9. Colaborador con rol READER intenta reposicionar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.patch(
        f"/api/diagram/attributes/{sec_2_id}/position",
        json={"position": 2},
    )
    assert resp_reader.status_code == 403

    # 10. Extraño -> 404 Not Found
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.patch(
        f"/api/diagram/attributes/{sec_2_id}/position",
        json={"position": 2},
    )
    assert resp_stranger.status_code == 404

    # 11. Atributo inexistente -> 404 Not Found
    app.dependency_overrides[get_current_user] = lambda: owner_user
    fake_id = str(uuid.uuid4())
    resp_not_found = client.patch(
        f"/api/diagram/attributes/{fake_id}/position",
        json={"position": 1},
    )
    assert resp_not_found.status_code == 404


def test_delete_diagram_attribute(
    client: TestClient,
    test_project: ProjectModel,
    test_class_with_attributes: DiagramClassModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Snapshot inicial
    resp_diagram = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp_diagram.status_code == 200
    cls_data = next(
        c for c in resp_diagram.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    pk_attr = next(a for a in cls_data["attributes"] if a["is_primary_key"])
    sec_1 = next(a for a in cls_data["attributes"] if a["name"] == "nombre")
    sec_2 = next(a for a in cls_data["attributes"] if a["name"] == "edad")
    sec_3 = next(a for a in cls_data["attributes"] if a["name"] == "activo")

    pk_id = pk_attr["id"]
    sec_1_id = sec_1["id"]
    sec_2_id = sec_2["id"]
    sec_3_id = sec_3["id"]

    # 1. Proteger PK: Intentar eliminar la llave primaria -> 409 Conflict
    resp_del_pk = client.delete(f"/api/diagram/attributes/{pk_id}")
    assert resp_del_pk.status_code == 409
    assert resp_del_pk.json()["error"]["code"] == "PRIMARY_KEY_CANNOT_BE_DELETED"

    # Verificar que la PK sigue existiendo y en posición 0
    resp_check_pk = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_after_pk = next(
        c for c in resp_check_pk.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    assert any(a["id"] == pk_id and a["position"] == 0 for a in cls_after_pk["attributes"])

    # 2. Eliminar un secundario intermedio (sec_2, posición 2) -> 204 No Content
    resp_del_sec2 = client.delete(f"/api/diagram/attributes/{sec_2_id}")
    assert resp_del_sec2.status_code == 204

    # Verificar compactación en el snapshot:
    # sec_2 ya no existe, sec_1 sigue en 1, sec_3 se compacta de posición 3 a posición 2
    resp_snap_after_del = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_snap_after_del = next(
        c for c in resp_snap_after_del.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    remaining_ids = [a["id"] for a in cls_snap_after_del["attributes"]]
    assert sec_2_id not in remaining_ids
    positions_after_del = {a["id"]: a["position"] for a in cls_snap_after_del["attributes"]}
    assert positions_after_del[pk_id] == 0
    assert positions_after_del[sec_1_id] == 1
    assert positions_after_del[sec_3_id] == 2

    # 3. Reintento idempotente de eliminación del mismo atributo ya eliminado -> 204 No Content
    resp_del_retry = client.delete(f"/api/diagram/attributes/{sec_2_id}")
    assert resp_del_retry.status_code == 204

    # 4. Eliminar atributo inexistente -> 204 No Content (idempotente)
    fake_id = str(uuid.uuid4())
    resp_del_fake = client.delete(f"/api/diagram/attributes/{fake_id}")
    assert resp_del_fake.status_code == 204

    # 5. Colaborador con rol READER intenta eliminar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.delete(f"/api/diagram/attributes/{sec_1_id}")
    assert resp_reader.status_code == 403

    # 6. Extraño intentando eliminar un atributo existente -> 404 Not Found
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.delete(f"/api/diagram/attributes/{sec_1_id}")
    assert resp_stranger.status_code == 404

    # 7. Colaborador con rol EDITOR elimina sec_3 -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_del_sec3 = client.delete(f"/api/diagram/attributes/{sec_3_id}")
    assert resp_del_sec3.status_code == 204

    # 8. Propietario elimina sec_1 (el último secundario restante) -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_del_sec1 = client.delete(f"/api/diagram/attributes/{sec_1_id}")
    assert resp_del_sec1.status_code == 204

    # Verificar que la clase queda únicamente con la PK en posición 0
    resp_final = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_final = next(
        c for c in resp_final.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    assert len(cls_final["attributes"]) == 1
    assert cls_final["attributes"][0]["id"] == pk_id
    assert cls_final["attributes"][0]["position"] == 0
    assert cls_final["attributes"][0]["is_primary_key"] is True

