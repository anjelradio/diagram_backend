import uuid
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from tests.modules.diagram.conftest import (
    create_test_attribute,
    create_test_class,
    create_test_relation,
)


def test_get_diagram_snapshot_with_relations_and_fk_metadata(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    project_id = test_project.id

    # 1. Crear dos clases base con PK
    cls_author = create_test_class(session, project_id, name="Author", position_x=100.0, position_y=100.0)
    attr_author_pk = create_test_attribute(session, cls_author.id, name="id", data_type="UUID", position=0, is_primary_key=True)

    cls_book = create_test_class(session, project_id, name="Book", position_x=400.0, position_y=100.0)
    attr_book_pk = create_test_attribute(session, cls_book.id, name="id", data_type="UUID", position=0, is_primary_key=True)

    # 2. Crear una relación 1:N con FK
    rel_1n_id = uuid.uuid4()
    rel_1n = create_test_relation(
        session,
        project_id,
        source_class_id=cls_author.id,
        target_class_id=cls_book.id,
        relation_id=rel_1n_id,
        name="AuthorBooks",
        relation_type="ASSOCIATION",
        source_cardinality="1",
        target_cardinality="0..*",
        source_handle="RIGHT_CENTER",
        target_handle="LEFT_CENTER",
    )
    attr_book_fk = create_test_attribute(
        session,
        cls_book.id,
        name="author_id",
        data_type="UUID",
        position=1,
        is_primary_key=False,
        is_nullable=False,
        is_foreign_key=True,
        referenced_class_id=cls_author.id,
        relation_id=rel_1n_id,
    )

    # 3. Crear una relación N:M con clase puente, PK y 2 FK
    cls_tag = create_test_class(session, project_id, name="Tag", position_x=700.0, position_y=100.0)
    attr_tag_pk = create_test_attribute(session, cls_tag.id, name="id", data_type="UUID", position=0, is_primary_key=True)

    bridge_cls = create_test_class(session, project_id, name="BookTag", position_x=550.0, position_y=280.0)
    attr_bridge_pk = create_test_attribute(session, bridge_cls.id, name="id", data_type="UUID", position=0, is_primary_key=True)

    rel_nm_id = uuid.uuid4()
    rel_nm = create_test_relation(
        session,
        project_id,
        source_class_id=cls_book.id,
        target_class_id=cls_tag.id,
        relation_id=rel_nm_id,
        name="",
        relation_type="ASSOCIATION",
        source_cardinality="0..*",
        target_cardinality="0..*",
        source_handle="RIGHT_CENTER",
        target_handle="LEFT_CENTER",
        bridge_class_id=bridge_cls.id,
        bridge_handle="TOP_CENTER",
    )

    attr_bridge_fk1 = create_test_attribute(
        session,
        bridge_cls.id,
        name="book_id",
        data_type="UUID",
        position=1,
        is_primary_key=False,
        is_nullable=False,
        is_foreign_key=True,
        referenced_class_id=cls_book.id,
        relation_id=rel_nm_id,
    )
    attr_bridge_fk2 = create_test_attribute(
        session,
        bridge_cls.id,
        name="tag_id",
        data_type="UUID",
        position=2,
        is_primary_key=False,
        is_nullable=False,
        is_foreign_key=True,
        referenced_class_id=cls_tag.id,
        relation_id=rel_nm_id,
    )

    session.commit()

    # 4. Obtener snapshot y validar
    resp = client.get(f"/api/projects/{project_id}/diagram")
    assert resp.status_code == 200
    data = resp.json()

    # Validar clases y metadatos FK
    assert len(data["classes"]) == 4  # Author, Book, Tag, BookTag
    book_data = next(c for c in data["classes"] if c["id"] == str(cls_book.id))
    assert len(book_data["attributes"]) == 2
    fk_attr_data = next(a for a in book_data["attributes"] if a["id"] == str(attr_book_fk.id))
    assert fk_attr_data["is_foreign_key"] is True
    assert fk_attr_data["referenced_class_id"] == str(cls_author.id)
    assert fk_attr_data["relation_id"] == str(rel_1n_id)

    # Validar relaciones top-level
    assert "relations" in data
    assert len(data["relations"]) == 2

    rel_1n_data = next(r for r in data["relations"] if r["id"] == str(rel_1n_id))
    assert rel_1n_data["name"] == "AuthorBooks"
    assert rel_1n_data["relation_type"] == "ASSOCIATION"
    assert rel_1n_data["source"]["class_id"] == str(cls_author.id)
    assert rel_1n_data["source"]["handle"] == "RIGHT_CENTER"
    assert rel_1n_data["target"]["class_id"] == str(cls_book.id)
    assert rel_1n_data["target"]["handle"] == "LEFT_CENTER"
    assert rel_1n_data["source_cardinality"] == "1"
    assert rel_1n_data["target_cardinality"] == "0..*"
    assert rel_1n_data["bridge"] is None

    rel_nm_data = next(r for r in data["relations"] if r["id"] == str(rel_nm_id))
    assert rel_nm_data["name"] == ""
    assert rel_nm_data["relation_type"] == "ASSOCIATION"
    assert rel_nm_data["bridge"] is not None
    assert rel_nm_data["bridge"]["class_id"] == str(bridge_cls.id)
    assert rel_nm_data["bridge"]["handle"] == "TOP_CENTER"


def test_get_diagram_snapshot_maintains_constant_query_count(
    client: TestClient,
    session: Session,
    test_engine,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que el snapshot mantiene una cantidad constante de consultas independientemente de N (T069)."""
    app.dependency_overrides[get_current_user] = lambda: owner_user
    project_id = test_project.id

    # Caso A: 2 clases y 1 relación
    c1 = create_test_class(session, project_id, name="A1")
    create_test_attribute(session, c1.id, name="id", position=0, is_primary_key=True)
    c2 = create_test_class(session, project_id, name="B1")
    create_test_attribute(session, c2.id, name="id", position=0, is_primary_key=True)
    r1 = create_test_relation(
        session, project_id, source_class_id=c1.id, target_class_id=c2.id
    )
    session.commit()

    queries_a = []

    def callback_a(conn, cursor, statement, parameters, context, executemany):
        queries_a.append(statement)

    event.listen(test_engine, "before_cursor_execute", callback_a)
    try:
        resp_a = client.get(f"/api/projects/{project_id}/diagram")
        assert resp_a.status_code == 200
    finally:
        event.remove(test_engine, "before_cursor_execute", callback_a)

    count_a = len(queries_a)

    # Caso B: Añadir 5 clases más y 4 relaciones adicionales
    prev_class = c2
    for i in range(2, 7):
        new_cls = create_test_class(session, project_id, name=f"C{i}")
        create_test_attribute(session, new_cls.id, name="id", position=0, is_primary_key=True)
        create_test_relation(
            session, project_id, source_class_id=prev_class.id, target_class_id=new_cls.id
        )
        prev_class = new_cls
    session.commit()

    queries_b = []

    def callback_b(conn, cursor, statement, parameters, context, executemany):
        queries_b.append(statement)

    event.listen(test_engine, "before_cursor_execute", callback_b)
    try:
        resp_b = client.get(f"/api/projects/{project_id}/diagram")
        assert resp_b.status_code == 200
        assert len(resp_b.json()["classes"]) == 7
        assert len(resp_b.json()["relations"]) == 6
    finally:
        event.remove(test_engine, "before_cursor_execute", callback_b)

    count_b = len(queries_b)

    assert count_a > 0
    assert count_a == count_b, f"Expected constant queries, got {count_a} vs {count_b}"
