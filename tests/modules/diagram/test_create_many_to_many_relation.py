import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_create_many_to_many_relation_atomic(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Crear dos clases base
    class_a_id = str(uuid.uuid4())
    class_b_id = str(uuid.uuid4())

    client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_a_id,
            "name": "Author",
            "position_x": 100.0,
            "position_y": 100.0,
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
            },
        },
    )

    client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_b_id,
            "name": "Book",
            "position_x": 400.0,
            "position_y": 100.0,
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
            },
        },
    )

    # 2. Preparar payload N:M con clase puente, PK y dos FK
    relation_id = str(uuid.uuid4())
    bridge_id = str(uuid.uuid4())
    bridge_pk_id = str(uuid.uuid4())
    fk_a_id = str(uuid.uuid4())
    fk_b_id = str(uuid.uuid4())

    payload = {
        "id": relation_id,
        "name": "AuthorsBooks",  # Debería normalizarse a "" según regla N:M
        "relation_type": "ASSOCIATION",
        "source": {
            "class_id": class_a_id,
            "handle": "RIGHT_CENTER",
            "cardinality": "0..*",
        },
        "target": {
            "class_id": class_b_id,
            "handle": "LEFT_CENTER",
            "cardinality": "1..*",
        },
        "materialization": {
            "strategy": "BRIDGE_CLASS",
            "foreign_attributes": [],
            "bridge_class": {
                "id": bridge_id,
                "name": "AuthorBook",
                "position_x": 250.0,
                "position_y": 280.0,
                "handle": "TOP_CENTER",
                "primary_attribute": {
                    "id": bridge_pk_id,
                    "name": "id",
                    "data_type": "UUID",
                    "position": 0,
                    "is_primary_key": True,
                    "is_nullable": False,
                },
                "foreign_attributes": [
                    {
                        "id": fk_a_id,
                        "class_id": bridge_id,
                        "name": "author_id",
                        "data_type": "UUID",
                        "position": 1,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": class_a_id,
                        "relation_id": relation_id,
                    },
                    {
                        "id": fk_b_id,
                        "class_id": bridge_id,
                        "name": "book_id",
                        "data_type": "UUID",
                        "position": 2,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": class_b_id,
                        "relation_id": relation_id,
                    },
                ],
            },
        },
    }

    # 3. Crear relación N:M -> 201 Created sin cuerpo
    resp = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=payload,
    )
    assert resp.status_code == 201
    assert not resp.content or resp.text == ""

    # 4. Verificar en base de datos
    session.expunge_all()

    rel = session.exec(
        select(DiagramRelationModel).where(
            DiagramRelationModel.id == uuid.UUID(relation_id)
        )
    ).first()
    assert rel is not None
    assert rel.name == "AuthorsBooks"  # Nombre persistido en N:M según US4
    assert rel.bridge_class_id == uuid.UUID(bridge_id)
    assert rel.bridge_handle == "TOP_CENTER"

    bridge_cls = session.exec(
        select(DiagramClassModel).where(DiagramClassModel.id == uuid.UUID(bridge_id))
    ).first()
    assert bridge_cls is not None
    assert bridge_cls.name == "AuthorBook"
    assert bridge_cls.position_x == 250.0
    assert bridge_cls.position_y == 280.0

    bridge_attrs = session.exec(
        select(DiagramAttributeModel)
        .where(DiagramAttributeModel.class_id == uuid.UUID(bridge_id))
        .order_by(DiagramAttributeModel.position)
    ).all()
    assert len(bridge_attrs) == 3

    # PK
    assert bridge_attrs[0].id == uuid.UUID(bridge_pk_id)
    assert bridge_attrs[0].is_primary_key is True
    assert bridge_attrs[0].is_foreign_key is False
    assert bridge_attrs[0].position == 0

    # FK 1
    assert bridge_attrs[1].id == uuid.UUID(fk_a_id)
    assert bridge_attrs[1].is_primary_key is False
    assert bridge_attrs[1].is_foreign_key is True
    assert bridge_attrs[1].referenced_class_id == uuid.UUID(class_a_id)
    assert bridge_attrs[1].relation_id == uuid.UUID(relation_id)
    assert bridge_attrs[1].position == 1

    # FK 2
    assert bridge_attrs[2].id == uuid.UUID(fk_b_id)
    assert bridge_attrs[2].is_primary_key is False
    assert bridge_attrs[2].is_foreign_key is True
    assert bridge_attrs[2].referenced_class_id == uuid.UUID(class_b_id)
    assert bridge_attrs[2].relation_id == uuid.UUID(relation_id)
    assert bridge_attrs[2].position == 2

    # 5. Reintento idempotente con exactamente la misma petición -> 204 No Content
    resp_idempotent = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=payload,
    )
    assert resp_idempotent.status_code == 204
    assert not resp_idempotent.content or resp_idempotent.text == ""

    # 6. Mismo ID con datos distintos (handle distinto) -> 409 Conflict
    conflict_payload = dict(payload)
    conflict_payload["source"] = {
        "class_id": class_a_id,
        "handle": "LEFT_TOP",
        "cardinality": "0..*",
    }
    resp_conflict = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json=conflict_payload,
    )
    assert resp_conflict.status_code == 409
