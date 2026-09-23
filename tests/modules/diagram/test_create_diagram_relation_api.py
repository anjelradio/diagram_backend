import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from tests.modules.diagram.conftest import create_test_attribute, create_test_class


def test_create_diagram_relation_api_contracts(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
):
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Setup clases
    c1 = create_test_class(session, project_id, name="ClassA")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="ClassB")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    session.commit()

    rel_id = str(uuid.uuid4())
    fk_id = str(uuid.uuid4())

    valid_payload = {
        "id": rel_id,
        "name": "AsociacionAB",
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
                    "name": "class_a_id",
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

    # Contrato 201: Owner crea con éxito -> 201 sin cuerpo
    resp_201 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=valid_payload,
    )
    assert resp_201.status_code == 201
    assert not resp_201.content or resp_201.text == ""

    # Contrato 204: Replay idempotente con payload idéntico -> 204 sin cuerpo
    resp_204 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=valid_payload,
    )
    assert resp_204.status_code == 204
    assert not resp_204.content or resp_204.text == ""

    # Contrato 409: Conflicto reutilizando ID con nombre distinto
    conflict_payload = dict(valid_payload)
    conflict_payload["name"] = "NombreCambiado"
    resp_409 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=conflict_payload,
    )
    assert resp_409.status_code == 409

    # Contrato 403: Lector no tiene permiso de escritura
    app.dependency_overrides[get_current_user] = lambda: reader_user
    new_rel_id = str(uuid.uuid4())
    reader_payload = dict(valid_payload)
    reader_payload["id"] = new_rel_id
    reader_payload["materialization"]["foreign_attributes"][0]["id"] = str(uuid.uuid4())
    reader_payload["materialization"]["foreign_attributes"][0]["relation_id"] = new_rel_id
    resp_403 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=reader_payload,
    )
    assert resp_403.status_code == 403

    # Contrato 404: Stranger intenta acceder a proyecto ajeno
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_404 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=reader_payload,
    )
    assert resp_404.status_code == 404

    # Contrato 422: Validación Pydantic (campo faltante, extra forbidden, handle inválido)
    app.dependency_overrides[get_current_user] = lambda: owner_user
    invalid_schema_payload = dict(valid_payload)
    invalid_schema_payload["source"]["handle"] = "INVALID_HANDLE"
    resp_422 = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=invalid_schema_payload,
    )
    assert resp_422.status_code == 422


def test_create_self_referencing_relation_api(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    c1 = create_test_class(session, project_id, name="Category")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    session.commit()

    rel_id = str(uuid.uuid4())
    fk_id = str(uuid.uuid4())

    # 1. Self-referencing 1:N association with is_nullable=True
    self_payload = {
        "id": rel_id,
        "name": "padre_de",
        "relation_type": "ASSOCIATION",
        "source": {
            "class_id": str(c1.id),
            "handle": "RIGHT_TOP",
            "cardinality": "0..1",
        },
        "target": {
            "class_id": str(c1.id),
            "handle": "RIGHT_BOTTOM",
            "cardinality": "0..*",
        },
        "materialization": {
            "strategy": "FOREIGN_KEY",
            "foreign_attributes": [
                {
                    "id": fk_id,
                    "class_id": str(c1.id),
                    "name": "parent_category_id",
                    "data_type": "UUID",
                    "position": 1,
                    "is_primary_key": False,
                    "is_nullable": True,
                    "is_foreign_key": True,
                    "referenced_class_id": str(c1.id),
                    "relation_id": rel_id,
                }
            ],
        },
    }

    resp = client.post(f"/api/projects/{project_id}/diagram/relations", json=self_payload)
    assert resp.status_code == 201

    # Verify snapshot contains relation and self-referencing nullable FK
    resp_snap = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_snap.status_code == 200
    classes = resp_snap.json()["classes"]
    relations = resp_snap.json()["relations"]
    assert len(relations) == 1
    assert relations[0]["source"]["class_id"] == str(c1.id)
    assert relations[0]["target"]["class_id"] == str(c1.id)

    cat_class = next(c for c in classes if c["id"] == str(c1.id))
    assert len(cat_class["attributes"]) == 2
    fk_attr = next(a for a in cat_class["attributes"] if a["id"] == fk_id)
    assert fk_attr["is_foreign_key"] is True
    assert fk_attr["referenced_class_id"] == str(c1.id)
    assert fk_attr["is_nullable"] is True

    # 2. Reject self-referencing GENERALIZATION
    gen_id = str(uuid.uuid4())
    gen_payload = {
        "id": gen_id,
        "name": "",
        "relation_type": "GENERALIZATION",
        "source": {
            "class_id": str(c1.id),
            "handle": "TOP_CENTER",
            "cardinality": None,
        },
        "target": {
            "class_id": str(c1.id),
            "handle": "BOTTOM_CENTER",
            "cardinality": None,
        },
        "materialization": {
            "strategy": "SHARED_PRIMARY_KEY",
            "shared_primary_key": {
                "attribute_id": str(uuid.uuid4()),
                "class_id": str(c1.id),
                "referenced_class_id": str(c1.id),
                "relation_id": gen_id,
            },
        },
    }
    resp_gen = client.post(f"/api/projects/{project_id}/diagram/relations", json=gen_payload)
    assert resp_gen.status_code == 422 or resp_gen.status_code == 400

    # 3. Reject self-referencing with identical handles
    same_handle_id = str(uuid.uuid4())
    same_handle_payload = dict(self_payload)
    same_handle_payload["id"] = same_handle_id
    same_handle_payload["source"]["handle"] = "RIGHT_TOP"
    same_handle_payload["target"]["handle"] = "RIGHT_TOP"
    same_handle_payload["materialization"]["foreign_attributes"][0]["id"] = str(uuid.uuid4())
    same_handle_payload["materialization"]["foreign_attributes"][0]["relation_id"] = same_handle_id

    resp_same_handle = client.post(
        f"/api/projects/{project_id}/diagram/relations", json=same_handle_payload
    )
    assert resp_same_handle.status_code == 422 or resp_same_handle.status_code == 400

