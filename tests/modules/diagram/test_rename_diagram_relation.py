import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from tests.modules.diagram.conftest import create_test_attribute, create_test_class


def test_rename_diagram_relation(
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

    # 1. Setup clases
    c1 = create_test_class(session, project_id, name="Author")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="Book")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    session.commit()

    rel_id = str(uuid.uuid4())
    fk_id = str(uuid.uuid4())

    create_payload = {
        "id": rel_id,
        "name": "Escribe",
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
                    "name": "author_id",
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
    }

    resp_create = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=create_payload,
    )
    assert resp_create.status_code == 201

    # 2. Propietario renombra la relación exitosamente -> 204 No Content
    resp_rename = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "Publica"},
    )
    assert resp_rename.status_code == 204
    assert resp_rename.content == b""

    # Verificar en snapshot que el nombre cambió
    resp_snapshot = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_snapshot.status_code == 200
    relations = resp_snapshot.json()["relations"]
    rel = next(r for r in relations if r["id"] == rel_id)
    assert rel["name"] == "Publica"

    # 3. Normalización de espacios en blanco ("  Redacta  ") -> 204
    resp_trim = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "  Redacta  "},
    )
    assert resp_trim.status_code == 204
    resp_snapshot_2 = client.get(f"/api/projects/{project_id}/diagram")
    rel_2 = next(r for r in resp_snapshot_2.json()["relations"] if r["id"] == rel_id)
    assert rel_2["name"] == "Redacta"

    # 4. Colaborador EDITOR puede renombrar -> 204
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_editor = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "Edita"},
    )
    assert resp_editor.status_code == 204

    # 5. Colaborador READER intenta renombrar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "IntentoReader"},
    )
    assert resp_reader.status_code == 403

    # 6. No miembro (stranger) intenta renombrar -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_stranger = client.patch(
        f"/api/diagram/relations/{rel_id}/name",
        json={"name": "IntentoStranger"},
    )
    assert resp_stranger.status_code == 404

    # 7. Relación inexistente -> 404
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_fake = client.patch(
        f"/api/diagram/relations/{uuid.uuid4()}/name",
        json={"name": "Fantasma"},
    )
    assert resp_fake.status_code == 404

    # 8. Asociación N:M (many-to-many): admite nombre inicial y permite renombrar
    nm_rel_id = str(uuid.uuid4())
    bridge_id = str(uuid.uuid4())
    nm_payload = {
        "id": nm_rel_id,
        "name": "Nueva relación",
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
                "id": bridge_id,
                "name": "AuthorBook",
                "position_x": 200.0,
                "position_y": 280.0,
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
                        "class_id": bridge_id,
                        "name": "author_id",
                        "data_type": "UUID",
                        "position": 1,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": str(c1.id),
                        "relation_id": nm_rel_id,
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "class_id": bridge_id,
                        "name": "book_id",
                        "data_type": "UUID",
                        "position": 2,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": str(c2.id),
                        "relation_id": nm_rel_id,
                    },
                ],
            },
        },
    }

    resp_nm_create = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=nm_payload,
    )
    assert resp_nm_create.status_code == 201

    # Renombrar relación N:M debe ser exitoso -> 204 No Content
    resp_nm_rename = client.patch(
        f"/api/diagram/relations/{nm_rel_id}/name",
        json={"name": "Autores y Libros"},
    )
    assert resp_nm_rename.status_code == 204

    resp_nm_snapshot = client.get(f"/api/projects/{project_id}/diagram")
    nm_rel_snap = next(r for r in resp_nm_snapshot.json()["relations"] if r["id"] == nm_rel_id)
    assert nm_rel_snap["name"] == "Autores y Libros"

    # 9. Relaciones no asociativas: rechazan rename con 409 Conflict
    c3 = create_test_class(session, project_id, name="ParentClass")
    create_test_attribute(session, c3.id, name="id", position=0, is_primary_key=True)
    c4 = create_test_class(session, project_id, name="ChildClass")
    c4_pk = create_test_attribute(session, c4.id, name="id", position=0, is_primary_key=True)
    session.commit()

    gen_rel_id = str(uuid.uuid4())
    gen_payload = {
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
    }
    resp_gen_create = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=gen_payload,
    )
    assert resp_gen_create.status_code == 201

    # Intentar renombrar relación no asociativa debe ser 409 Conflict
    resp_gen_rename = client.patch(
        f"/api/diagram/relations/{gen_rel_id}/name",
        json={"name": "HeredaDe"},
    )
    assert resp_gen_rename.status_code == 409

