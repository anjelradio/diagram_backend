import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


@pytest.fixture
def base_class_and_attribute(
    client: TestClient,
    test_project: ProjectModel,
    test_class_with_attributes: DiagramClassModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp.status_code == 200
    cls = next(
        c for c in resp.json()["classes"] if c["id"] == str(test_class_with_attributes.id)
    )
    sec_attr = next(a for a in cls["attributes"] if not a["is_primary_key"])
    return test_class_with_attributes.id, sec_attr["id"]


def test_diagram_attribute_permissions_matrix(
    client: TestClient,
    test_project: ProjectModel,
    base_class_and_attribute,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    removed_user: AuthUser,
    banned_user: AuthUser,
    stranger_user: AuthUser,
):
    class_id, attr_id = base_class_and_attribute
    project_id = test_project.id

    # 1. Propietario (Owner) -> Acceso total de lectura y escritura
    app.dependency_overrides[get_current_user] = lambda: owner_user

    resp_read = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_read.status_code == 200
    assert "can_edit" not in resp_read.json()

    new_id_owner = str(uuid.uuid4())
    resp_create = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={"id": new_id_owner, "name": "owner_field", "position": 4},
    )
    assert resp_create.status_code == 201

    resp_update = client.patch(
        f"/api/diagram/attributes/{attr_id}",
        json={"name": "updated_by_owner"},
    )
    assert resp_update.status_code == 204

    resp_repo = client.patch(
        f"/api/diagram/attributes/{attr_id}/position",
        json={"position": 2},
    )
    assert resp_repo.status_code == 204

    resp_del = client.delete(f"/api/diagram/attributes/{new_id_owner}")
    assert resp_del.status_code == 204

    # 2. Miembro EDITOR activo -> Acceso total de lectura y escritura
    app.dependency_overrides[get_current_user] = lambda: editor_user

    resp_read_ed = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_read_ed.status_code == 200
    assert "can_edit" not in resp_read_ed.json()

    new_id_ed = str(uuid.uuid4())
    resp_create_ed = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={"id": new_id_ed, "name": "editor_field", "position": 4},
    )
    assert resp_create_ed.status_code == 201

    resp_update_ed = client.patch(
        f"/api/diagram/attributes/{attr_id}",
        json={"name": "updated_by_editor"},
    )
    assert resp_update_ed.status_code == 204

    resp_repo_ed = client.patch(
        f"/api/diagram/attributes/{attr_id}/position",
        json={"position": 1},
    )
    assert resp_repo_ed.status_code == 204

    resp_del_ed = client.delete(f"/api/diagram/attributes/{new_id_ed}")
    assert resp_del_ed.status_code == 204

    # 3. Miembro READER activo -> Lectura permitida (sin can_edit), mutaciones denegadas (403)
    app.dependency_overrides[get_current_user] = lambda: reader_user

    resp_read_rd = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_read_rd.status_code == 200
    assert "can_edit" not in resp_read_rd.json()

    resp_create_rd = client.post(
        f"/api/diagram/classes/{class_id}/attributes",
        json={"id": str(uuid.uuid4()), "name": "reader_field", "position": 4},
    )
    assert resp_create_rd.status_code == 403

    resp_update_rd = client.patch(
        f"/api/diagram/attributes/{attr_id}",
        json={"name": "updated_by_reader"},
    )
    assert resp_update_rd.status_code == 403

    resp_repo_rd = client.patch(
        f"/api/diagram/attributes/{attr_id}/position",
        json={"position": 1},
    )
    assert resp_repo_rd.status_code == 403

    resp_del_rd = client.delete(f"/api/diagram/attributes/{attr_id}")
    assert resp_del_rd.status_code == 403

    # 4. Usuarios sin acceso (Stranger, Banned, Removed) -> 404 en todas las operaciones
    for unauthorized_user in [stranger_user, banned_user, removed_user]:
        app.dependency_overrides[get_current_user] = lambda u=unauthorized_user: u

        assert client.get(f"/api/projects/{project_id}/diagram").status_code == 404
        assert (
            client.post(
                f"/api/diagram/classes/{class_id}/attributes",
                json={"id": str(uuid.uuid4()), "name": "forbidden", "position": 4},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/diagram/attributes/{attr_id}",
                json={"name": "forbidden"},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/diagram/attributes/{attr_id}/position",
                json={"position": 1},
            ).status_code
            == 404
        )
        assert client.delete(f"/api/diagram/attributes/{attr_id}").status_code == 404

    # 5. Sin autenticación -> 401 en todas las operaciones
    app.dependency_overrides.pop(get_current_user, None)

    assert client.get(f"/api/projects/{project_id}/diagram").status_code == 401
    assert (
        client.post(
            f"/api/diagram/classes/{class_id}/attributes",
            json={"id": str(uuid.uuid4()), "name": "unauth", "position": 4},
        ).status_code
        == 401
    )
    assert (
        client.patch(
            f"/api/diagram/attributes/{attr_id}",
            json={"name": "unauth"},
        ).status_code
        == 401
    )
    assert (
        client.patch(
            f"/api/diagram/attributes/{attr_id}/position",
            json={"position": 1},
        ).status_code
        == 401
    )
    assert client.delete(f"/api/diagram/attributes/{attr_id}").status_code == 401


def test_derived_foreign_key_and_shared_primary_key_permissions(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que en una FK secundaria solo name sea editable, y que en una PK compartida todo esté bloqueado."""
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Setup: 2 clases con PK normal
    from tests.modules.diagram.conftest import create_test_attribute, create_test_class

    c1 = create_test_class(session, project_id, name="Company")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="Employee")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    session.commit()

    # 1. Crear relación 1:N que genera FK secundaria en Employee
    rel_id = str(uuid.uuid4())
    fk_id = str(uuid.uuid4())
    resp_rel = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json={
            "id": rel_id,
            "name": "Emplea",
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
                        "name": "company_id",
                        "data_type": "UUID",
                        "position": 1,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": str(c1.id),
                        "relation_id": rel_id,
                    }
                ],
                "shared_primary_key": None,
                "bridge_class": None,
            },
        },
    )
    assert resp_rel.status_code == 201

    # FK secundaria: Renombrar permitido -> 204
    resp_rename_fk = client.patch(
        f"/api/diagram/attributes/{fk_id}",
        json={"name": "empresa_id"},
    )
    assert resp_rename_fk.status_code == 204

    # FK secundaria: Cambiar tipo bloqueado -> 409
    resp_type_fk = client.patch(
        f"/api/diagram/attributes/{fk_id}",
        json={"data_type": "TEXT"},
    )
    assert resp_type_fk.status_code == 409

    # FK secundaria: Cambiar nulabilidad bloqueado -> 409
    resp_null_fk = client.patch(
        f"/api/diagram/attributes/{fk_id}",
        json={"is_nullable": True},
    )
    assert resp_null_fk.status_code == 409

    # FK secundaria: Reposicionar bloqueado -> 409
    resp_repo_fk = client.patch(
        f"/api/diagram/attributes/{fk_id}/position",
        json={"position": 2},
    )
    assert resp_repo_fk.status_code == 409

    # FK secundaria: Eliminar directamente bloqueado -> 409
    resp_del_fk = client.delete(f"/api/diagram/attributes/{fk_id}")
    assert resp_del_fk.status_code == 409

    # 2. Generalización: Subclase comparte PK con Superclase
    c3 = create_test_class(session, project_id, name="Vehicle")
    create_test_attribute(session, c3.id, name="id", position=0, is_primary_key=True)
    c4 = create_test_class(session, project_id, name="Car")
    c4_pk = create_test_attribute(session, c4.id, name="id", position=0, is_primary_key=True)
    session.commit()

    gen_rel_id = str(uuid.uuid4())
    resp_gen = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json={
            "id": gen_rel_id,
            "name": "",
            "relation_type": "GENERALIZATION",
            "source": {
                "class_id": str(c4.id),
                "handle": "TOP_CENTER",
                "cardinality": None,
            },
            "target": {
                "class_id": str(c3.id),
                "handle": "BOTTOM_CENTER",
                "cardinality": None,
            },
            "materialization": {
                "strategy": "SHARED_PRIMARY_KEY",
                "foreign_attributes": [],
                "shared_primary_key": {
                    "attribute_id": str(c4_pk.id),
                    "class_id": str(c4.id),
                    "referenced_class_id": str(c3.id),
                    "relation_id": gen_rel_id,
                },
                "bridge_class": None,
            },
        },
    )
    assert resp_gen.status_code == 201

    # Verificar que en el snapshot la PK de la subclase ahora tiene is_primary_key=True e is_foreign_key=True
    resp_snap = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_snap.status_code == 200
    c4_data = next(c for c in resp_snap.json()["classes"] if c["id"] == str(c4.id))
    c4_pk_data = next(a for a in c4_data["attributes"] if a["id"] == str(c4_pk.id))
    assert c4_pk_data["is_primary_key"] is True
    assert c4_pk_data["is_foreign_key"] is True

    # PK compartida: Renombrar BLOQUEADO -> 409 Conflict
    resp_rename_shared_pk = client.patch(
        f"/api/diagram/attributes/{c4_pk.id}",
        json={"name": "vehicle_ref"},
    )
    assert resp_rename_shared_pk.status_code == 409

    # PK compartida: Cambiar tipo bloqueado -> 409 Conflict
    resp_type_shared_pk = client.patch(
        f"/api/diagram/attributes/{c4_pk.id}",
        json={"data_type": "TEXT"},
    )
    assert resp_type_shared_pk.status_code == 409

    # PK compartida: Cambiar nulabilidad bloqueado -> 409 Conflict
    resp_null_shared_pk = client.patch(
        f"/api/diagram/attributes/{c4_pk.id}",
        json={"is_nullable": True},
    )
    assert resp_null_shared_pk.status_code == 409

    # PK compartida: Reposicionar bloqueado -> 409 Conflict
    resp_repo_shared_pk = client.patch(
        f"/api/diagram/attributes/{c4_pk.id}/position",
        json={"position": 1},
    )
    assert resp_repo_shared_pk.status_code == 409

    # PK compartida: Eliminar bloqueado -> 409 Conflict
    resp_del_shared_pk = client.delete(f"/api/diagram/attributes/{c4_pk.id}")
    assert resp_del_shared_pk.status_code == 409
