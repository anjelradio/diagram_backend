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


def test_create_secondary_diagram_attribute(
    client: TestClient,
    test_project: ProjectModel,
    test_class: DiagramClassModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    class_id = test_class.id
    attr_id_1 = str(uuid.uuid4())

    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Propietario crea atributo secundario en position 1 -> 201 Created sin cuerpo
    resp_create_1 = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_1,
            "name": "atributo",
            "position": 1,
        },
    )
    assert resp_create_1.status_code == 201
    assert not resp_create_1.content or resp_create_1.text == ""

    # Verificar creación y valores por defecto a través del snapshot
    resp_diag_check = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp_diag_check.status_code == 200
    cls_check = next(c for c in resp_diag_check.json()["classes"] if c["id"] == str(class_id))
    attr_1 = next(a for a in cls_check["attributes"] if a["id"] == attr_id_1)
    assert attr_1["name"] == "atributo"
    assert attr_1["data_type"] is None
    assert attr_1["position"] == 1
    assert attr_1["is_primary_key"] is False
    assert attr_1["is_nullable"] is True

    # 2. Reintento idempotente con exactamente los mismos datos -> 204 No Content
    resp_retry = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_1,
            "name": "atributo",
            "position": 1,
        },
    )
    assert resp_retry.status_code == 204
    assert not resp_retry.content or resp_retry.text == ""

    # 3. Mismo UUID con nombre distinto -> 409 Conflict
    resp_conflict_id = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_1,
            "name": "otro_nombre",
            "position": 1,
        },
    )
    assert resp_conflict_id.status_code == 409

    # 4. Crear segundo atributo con el MISMO nombre ("atributo") en position 2 -> 201 Created (permitido) sin cuerpo
    attr_id_2 = str(uuid.uuid4())
    resp_create_2 = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_2,
            "name": "atributo",
            "position": 2,
        },
    )
    assert resp_create_2.status_code == 201
    assert not resp_create_2.content or resp_create_2.text == ""

    # 5. Insertar en position 1 (desplazando a los existentes en position 1 y 2) -> 201 Created sin cuerpo
    attr_id_3 = str(uuid.uuid4())
    resp_create_3 = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_3,
            "name": "primero_desplazado",
            "position": 1,
        },
    )
    assert resp_create_3.status_code == 201
    assert not resp_create_3.content or resp_create_3.text == ""

    # Verificar posiciones en el snapshot completo:
    # PK en 0, attr_id_3 en 1, attr_id_1 en 2, attr_id_2 en 3
    resp_diagram = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp_diagram.status_code == 200
    cls_data = next(c for c in resp_diagram.json()["classes"] if c["id"] == str(class_id))
    positions = {a["id"]: a["position"] for a in cls_data["attributes"]}
    assert positions[attr_id_3] == 1
    assert positions[attr_id_1] == 2
    assert positions[attr_id_2] == 3

    # 6. Intentar crear en posición 0 (reservada para PK) -> 400 / 422
    resp_pos_0 = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": str(uuid.uuid4()),
            "name": "invalido",
            "position": 0,
        },
    )
    assert resp_pos_0.status_code in (400, 422)

    # 7. Intentar crear más allá de la siguiente posición válida (hay 4 atributos: 0, 1, 2, 3 -> max pos 4)
    # Mandar position 10 -> 400 / 422
    resp_pos_far = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": str(uuid.uuid4()),
            "name": "invalido_lejos",
            "position": 10,
        },
    )
    assert resp_pos_far.status_code in (400, 422)

    # 8. Colaborador con rol EDITOR crea atributo -> 201 Created sin cuerpo
    app.dependency_overrides[get_current_user] = lambda: editor_user
    attr_id_editor = str(uuid.uuid4())
    resp_editor = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": attr_id_editor,
            "name": "creado_por_editor",
            "position": 4,
        },
    )
    assert resp_editor.status_code == 201
    assert not resp_editor.content or resp_editor.text == ""

    # 9. Colaborador con rol READER intenta crear atributo -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": str(uuid.uuid4()),
            "name": "creado_por_reader",
            "position": 5,
        },
    )
    assert resp_reader.status_code == 403

    # 10. Stranger -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={
            "id": str(uuid.uuid4()),
            "name": "creado_por_extrano",
            "position": 5,
        },
    )
    assert resp_stranger.status_code == 404

    # 11. Clase inexistente -> 404
    app.dependency_overrides[get_current_user] = lambda: owner_user
    fake_class_id = str(uuid.uuid4())
    resp_not_found = client.post(
        f"/api/diagram/classes/{fake_class_id}/attributes",
        json={
            "id": str(uuid.uuid4()),
            "name": "fantasma",
            "position": 1,
        },
    )
    assert resp_not_found.status_code == 404


def test_update_diagram_attribute(
    client: TestClient,
    test_project: ProjectModel,
    test_class_with_attributes: DiagramClassModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Obtener el snapshot para conocer los IDs de atributos
    resp_diagram = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp_diagram.status_code == 200
    cls_data = next(
        c for c in resp_diagram.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    pk_attr = next(a for a in cls_data["attributes"] if a["is_primary_key"])
    sec_attr = next(a for a in cls_data["attributes"] if not a["is_primary_key"] and a["position"] == 1)

    pk_id = pk_attr["id"]
    sec_id = sec_attr["id"]

    # 1. Actualizar atributos secundarios: cambiar nombre
    resp_rename_sec = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"name": "primer_nombre"},
    )
    assert resp_rename_sec.status_code == 204

    # 2. Cambiar data_type a otro tipo válido
    resp_type_sec = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"data_type": "TIMESTAMP"},
    )
    assert resp_type_sec.status_code == 204

    # 3. Cambiar data_type a null (desasignar tipo)
    resp_null_type_sec = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"data_type": None},
    )
    assert resp_null_type_sec.status_code == 204

    # 4. Cambiar is_nullable a False
    resp_nullable_sec = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"is_nullable": False},
    )
    assert resp_nullable_sec.status_code == 204

    # Verificar estado del atributo secundario en el snapshot
    resp_check = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_data_check = next(
        c for c in resp_check.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    sec_updated = next(a for a in cls_data_check["attributes"] if a["id"] == sec_id)
    assert sec_updated["name"] == "primer_nombre"
    assert sec_updated["data_type"] is None
    assert sec_updated["is_nullable"] is False

    # 5. Proteger PK: Renombrar PK está totalmente prohibido -> 409 Conflict
    resp_rename_pk = client.patch(
        f"/api/diagram/attributes/{pk_id}",
        json={"name": "identificador_unico"},
    )
    assert resp_rename_pk.status_code == 409

    # Verificar que los datos de la PK no cambiaron en absoluto
    resp_check_pk = client.get(f"/api/projects/{test_project.id}/diagram")
    cls_data_pk = next(
        c for c in resp_check_pk.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    pk_updated = next(a for a in cls_data_pk["attributes"] if a["id"] == pk_id)
    assert pk_updated["name"] == "id"
    assert pk_updated["data_type"] == "UUID"
    assert pk_updated["position"] == 0
    assert pk_updated["is_nullable"] is False
    assert pk_updated["is_primary_key"] is True

    # 6. Proteger PK: Intentar cambiar data_type de PK -> 409 Conflict
    resp_pk_type = client.patch(
        f"/api/diagram/attributes/{pk_id}",
        json={"data_type": "TEXT"},
    )
    assert resp_pk_type.status_code == 409

    # 7. Proteger PK: Intentar poner data_type=None en PK -> 409 Conflict
    resp_pk_null_type = client.patch(
        f"/api/diagram/attributes/{pk_id}",
        json={"data_type": None},
    )
    assert resp_pk_null_type.status_code == 409

    # 8. Proteger PK: Intentar poner is_nullable=True en PK -> 409 Conflict
    resp_pk_nullable = client.patch(
        f"/api/diagram/attributes/{pk_id}",
        json={"is_nullable": True},
    )
    assert resp_pk_nullable.status_code == 409

    # 9. Validaciones de esquema: cuerpo vacío -> 422
    resp_empty = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={},
    )
    assert resp_empty.status_code == 422

    # 10. Validaciones de esquema: enviar is_primary_key -> 422 (extra="forbid")
    resp_extra_pk = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"is_primary_key": True},
    )
    assert resp_extra_pk.status_code == 422

    # 11. Validaciones de esquema: enviar position -> 422 (extra="forbid")
    resp_extra_pos = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"position": 2},
    )
    assert resp_extra_pos.status_code == 422

    # 12. Validaciones de esquema: nombre vacío o whitespace
    resp_empty_name = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"name": ""},
    )
    assert resp_empty_name.status_code == 422

    # 13. Colaborador con rol EDITOR puede actualizar -> 204
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_editor = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"name": "editado_por_editor"},
    )
    assert resp_editor.status_code == 204

    # 14. Colaborador con rol READER -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"name": "intento_reader"},
    )
    assert resp_reader.status_code == 403

    # 15. Extraño -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.patch(
        f"/api/diagram/attributes/{sec_id}",
        json={"name": "intento_extrano"},
    )
    assert resp_stranger.status_code == 404

    # 16. Atributo inexistente -> 404
    app.dependency_overrides[get_current_user] = lambda: owner_user
    fake_attr_id = str(uuid.uuid4())
    resp_not_found = client.patch(
        f"/api/diagram/attributes/{fake_attr_id}",
        json={"name": "fantasma"},
    )
    assert resp_not_found.status_code == 404

