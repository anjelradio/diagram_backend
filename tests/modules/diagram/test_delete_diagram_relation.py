import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from tests.modules.diagram.conftest import create_test_attribute, create_test_class


def test_delete_diagram_relation_and_cascades(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Setup clases: Base, Subclase, Destino
    c1 = create_test_class(session, project_id, name="Company")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="Employee")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    create_test_attribute(session, c2.id, name="name", position=1, is_primary_key=False)
    session.commit()

    rel_1n_id = str(uuid.uuid4())
    fk_attr_id = str(uuid.uuid4())

    # Crear relación 1:N
    payload_1n = {
        "id": rel_1n_id,
        "name": "Employs",
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
                    "id": fk_attr_id,
                    "class_id": str(c2.id),
                    "name": "company_id",
                    "data_type": "UUID",
                    "position": 2,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(c1.id),
                    "relation_id": rel_1n_id,
                }
            ],
            "shared_primary_key": None,
            "bridge_class": None,
        },
    }
    resp_create = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=payload_1n,
    )
    assert resp_create.status_code == 201

    # Permisos: READER intenta borrar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.delete(f"/api/diagram/relations/{rel_1n_id}")
    assert resp_reader.status_code == 403

    # Permisos: Stranger intenta borrar -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.delete(f"/api/diagram/relations/{rel_1n_id}")
    assert resp_stranger.status_code == 404

    # EDITOR elimina relación 1:N -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_del_1n = client.delete(f"/api/diagram/relations/{rel_1n_id}")
    assert resp_del_1n.status_code == 204
    assert resp_del_1n.content == b""

    # Idempotencia: borrar de nuevo la misma relación -> 204
    resp_idempotent = client.delete(f"/api/diagram/relations/{rel_1n_id}")
    assert resp_idempotent.status_code == 204

    # Verificar que el atributo FK desapareció y las posiciones están compactadas
    resp_snapshot = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_snapshot.status_code == 200
    classes = resp_snapshot.json()["classes"]
    emp_class = next(c for c in classes if c["id"] == str(c2.id))
    emp_attr_ids = [a["id"] for a in emp_class["attributes"]]
    assert fk_attr_id not in emp_attr_ids
    # Verificar posiciones contiguas (0, 1)
    positions = [a["position"] for a in emp_class["attributes"]]
    assert positions == [0, 1]
    # Verificar que la relación no está en el snapshot
    assert not any(r["id"] == rel_1n_id for r in resp_snapshot.json()["relations"])

    # 2. Probar Generalización y reversión de SHARED_PRIMARY_KEY
    app.dependency_overrides[get_current_user] = lambda: owner_user
    c_parent = create_test_class(session, project_id, name="Person")
    create_test_attribute(session, c_parent.id, name="id", position=0, is_primary_key=True)
    c_child = create_test_class(session, project_id, name="Student")
    student_pk = create_test_attribute(session, c_child.id, name="id", position=0, is_primary_key=True)
    session.commit()

    rel_gen_id = str(uuid.uuid4())
    payload_gen = {
        "id": rel_gen_id,
        "name": "",
        "relation_type": "GENERALIZATION",
        "source": {
            "class_id": str(c_child.id),
            "handle": "TOP_CENTER",
            "cardinality": None,
        },
        "target": {
            "class_id": str(c_parent.id),
            "handle": "BOTTOM_CENTER",
            "cardinality": None,
        },
        "materialization": {
            "strategy": "SHARED_PRIMARY_KEY",
            "foreign_attributes": [],
            "shared_primary_key": {
                "attribute_id": str(student_pk.id),
                "class_id": str(c_child.id),
                "referenced_class_id": str(c_parent.id),
                "relation_id": rel_gen_id,
            },
            "bridge_class": None,
        },
    }

    resp_gen = client.post(f"/api/projects/{project_id}/diagram/relations", json=payload_gen)
    assert resp_gen.status_code == 201

    # Eliminar relación de generalización -> 204
    resp_del_gen = client.delete(f"/api/diagram/relations/{rel_gen_id}")
    assert resp_del_gen.status_code == 204

    # Verificar que el atributo PK de student se revirtió (is_foreign_key=False, referenced_class_id=None, relation_id=None)
    resp_snap_gen = client.get(f"/api/projects/{project_id}/diagram")
    student_class = next(c for c in resp_snap_gen.json()["classes"] if c["id"] == str(c_child.id))
    st_pk_attr = next(a for a in student_class["attributes"] if a["id"] == str(student_pk.id))
    assert st_pk_attr["is_primary_key"] is True
    assert st_pk_attr["is_foreign_key"] is False
    assert st_pk_attr["referenced_class_id"] is None
    assert st_pk_attr["relation_id"] is None

    # 3. Probar eliminación de relación N:M (elimina la clase puente)
    rel_nm_id = str(uuid.uuid4())
    bridge_class_id = str(uuid.uuid4())
    payload_nm = {
        "id": rel_nm_id,
        "name": "CompanyEmployee",
        "relation_type": "ASSOCIATION",
        "source": {
            "class_id": str(c1.id),
            "handle": "BOTTOM_CENTER",
            "cardinality": "0..*",
        },
        "target": {
            "class_id": str(c2.id),
            "handle": "BOTTOM_CENTER",
            "cardinality": "0..*",
        },
        "materialization": {
            "strategy": "BRIDGE_CLASS",
            "foreign_attributes": [],
            "shared_primary_key": None,
            "bridge_class": {
                "id": bridge_class_id,
                "name": "CompanyEmployee",
                "position_x": 200.0,
                "position_y": 300.0,
                "handle": "TOP_CENTER",
                "primary_attribute": {
                    "id": str(uuid.uuid4()),
                    "name": "id",
                    "data_type": "UUID",
                    "position": 0,
                    "is_primary_key": True,
                    "is_nullable": False,
                },
                "foreign_attributes": [
                    {
                        "id": str(uuid.uuid4()),
                        "class_id": bridge_class_id,
                        "name": "company_id",
                        "data_type": "UUID",
                        "position": 1,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": str(c1.id),
                        "relation_id": rel_nm_id,
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "class_id": bridge_class_id,
                        "name": "employee_id",
                        "data_type": "UUID",
                        "position": 2,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": str(c2.id),
                        "relation_id": rel_nm_id,
                    },
                ],
            },
        },
    }

    resp_nm = client.post(f"/api/projects/{project_id}/diagram/relations", json=payload_nm)
    assert resp_nm.status_code == 201

    # Eliminar la relación N:M
    resp_del_nm = client.delete(f"/api/diagram/relations/{rel_nm_id}")
    assert resp_del_nm.status_code == 204

    # Verificar que la clase puente y la relación ya no existen en el snapshot, pero Company y Employee siguen vivos
    resp_snap_nm = client.get(f"/api/projects/{project_id}/diagram")
    snap_class_ids = [c["id"] for c in resp_snap_nm.json()["classes"]]
    assert bridge_class_id not in snap_class_ids
    assert str(c1.id) in snap_class_ids
    assert str(c2.id) in snap_class_ids
    assert not any(r["id"] == rel_nm_id for r in resp_snap_nm.json()["relations"])

    # 4. Probar eliminación en cascada al borrar una clase participante (DELETE /api/diagram/classes/{class_id})
    rel_cascade_id = str(uuid.uuid4())
    cascade_fk_id = str(uuid.uuid4())
    payload_cascade = {
        "id": rel_cascade_id,
        "name": "Asociada",
        "relation_type": "ASSOCIATION",
        "source": {
            "class_id": str(c1.id),
            "handle": "TOP_CENTER",
            "cardinality": "1",
        },
        "target": {
            "class_id": str(c2.id),
            "handle": "TOP_CENTER",
            "cardinality": "0..*",
        },
        "materialization": {
            "strategy": "FOREIGN_KEY",
            "foreign_attributes": [
                {
                    "id": cascade_fk_id,
                    "class_id": str(c2.id),
                    "name": "company_ref_id",
                    "data_type": "UUID",
                    "position": 2,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(c1.id),
                    "relation_id": rel_cascade_id,
                }
            ],
            "shared_primary_key": None,
            "bridge_class": None,
        },
    }
    client.post(f"/api/projects/{project_id}/diagram/relations", json=payload_cascade)

    # Eliminar c1 (Company)
    resp_del_class = client.delete(f"/api/diagram/classes/{c1.id}")
    assert resp_del_class.status_code == 204

    # Verificar que la relación se eliminó y que la FK en c2 (Employee) fue limpiada
    resp_snap_after = client.get(f"/api/projects/{project_id}/diagram")
    assert not any(r["id"] == rel_cascade_id for r in resp_snap_after.json()["relations"])
    c2_attrs = next(c for c in resp_snap_after.json()["classes"] if c["id"] == str(c2.id))["attributes"]
    assert not any(a["id"] == cascade_fk_id for a in c2_attrs)
