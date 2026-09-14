import uuid
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from tests.modules.diagram.conftest import create_test_attribute, create_test_class


def test_get_diagram_snapshot(
    client: TestClient,
    session,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    stranger_user: AuthUser,
    banned_user: AuthUser,
    removed_user: AuthUser,
):
    project_id = test_project.id

    # 1. Crear clases con atributos ordenados
    cls1 = create_test_class(session, project_id, name="Persona", position_x=10.0, position_y=20.0)
    create_test_attribute(session, cls1.id, name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)
    create_test_attribute(session, cls1.id, name="nombre", data_type="TEXT", position=1, is_primary_key=False, is_nullable=True)
    create_test_attribute(session, cls1.id, name="edad", data_type="INTEGER", position=2, is_primary_key=False, is_nullable=True)

    cls2 = create_test_class(session, project_id, name="Orden", position_x=100.0, position_y=200.0)
    create_test_attribute(session, cls2.id, name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)
    create_test_attribute(session, cls2.id, name="total", data_type="DECIMAL", position=1, is_primary_key=False, is_nullable=False)

    session.commit()

    # 2. Owner obtiene el snapshot -> 200 sin can_edit
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_owner = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_owner.status_code == 200
    data = resp_owner.json()
    assert "can_edit" not in data
    assert len(data["classes"]) == 2

    c1 = next(c for c in data["classes"] if c["id"] == str(cls1.id))
    assert c1["name"] == "Persona"
    assert c1["position_x"] == 10.0
    assert c1["position_y"] == 20.0
    # Verificar ausencia de fechas
    assert "created_date" not in c1
    assert "modified_date" not in c1
    assert "deleted_date" not in c1

    # Verificar atributos anidados y su orden
    attrs1 = c1["attributes"]
    assert len(attrs1) == 3
    assert [a["position"] for a in attrs1] == [0, 1, 2]
    assert attrs1[0]["name"] == "id"
    assert attrs1[0]["data_type"] == "UUID"
    assert attrs1[0]["is_primary_key"] is True
    assert attrs1[0]["is_nullable"] is False
    assert "created_date" not in attrs1[0]

    assert attrs1[1]["name"] == "nombre"
    assert attrs1[1]["data_type"] == "TEXT"
    assert attrs1[1]["is_primary_key"] is False
    assert attrs1[1]["is_nullable"] is True

    assert attrs1[2]["name"] == "edad"
    assert attrs1[2]["data_type"] == "INTEGER"

    # 3. Reader obtiene el snapshot -> 200 sin can_edit
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_reader = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_reader.status_code == 200
    reader_data = resp_reader.json()
    assert "can_edit" not in reader_data
    assert len(reader_data["classes"]) == 2

    # 4. Editor obtiene el snapshot -> 200 sin can_edit
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_editor = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_editor.status_code == 200
    assert "can_edit" not in resp_editor.json()

    # 5. Stranger -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    assert client.get(f"/api/projects/{project_id}/diagram").status_code == 404

    # 6. Banned -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    assert client.get(f"/api/projects/{project_id}/diagram").status_code == 404

    # 7. Removed -> 404
    app.dependency_overrides[get_current_user] = lambda: removed_user
    assert client.get(f"/api/projects/{project_id}/diagram").status_code == 404


def test_get_diagram_snapshot_empty_project(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp = client.get(f"/api/projects/{test_project.id}/diagram")
    assert resp.status_code == 200
    data = resp.json()
    assert data["classes"] == []
    assert "can_edit" not in data


def test_get_diagram_snapshot_query_count_is_constant(
    client: TestClient,
    session,
    test_engine,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que el snapshot se resuelve con una cantidad constante de consultas (anti-N+1)."""
    from sqlalchemy import event

    app.dependency_overrides[get_current_user] = lambda: owner_user
    project_id = test_project.id

    # Caso A: 1 clase con 2 atributos
    cls1 = create_test_class(
        session, project_id, name="Clase1", position_x=0.0, position_y=0.0
    )
    create_test_attribute(
        session, cls1.id, name="id", position=0, is_primary_key=True
    )
    create_test_attribute(
        session, cls1.id, name="a1", position=1, is_primary_key=False
    )
    session.commit()

    queries_case_a = []

    def callback_a(conn, cursor, statement, parameters, context, executemany):
        queries_case_a.append(statement)

    event.listen(test_engine, "before_cursor_execute", callback_a)
    try:
        resp_a = client.get(f"/api/projects/{project_id}/diagram")
        assert resp_a.status_code == 200
    finally:
        event.remove(test_engine, "before_cursor_execute", callback_a)

    count_a = len(queries_case_a)

    # Caso B: Añadir 5 clases adicionales con múltiples atributos cada una
    for i in range(2, 7):
        clsi = create_test_class(
            session, project_id, name=f"Clase{i}", position_x=float(i), position_y=float(i)
        )
        create_test_attribute(
            session, clsi.id, name="id", position=0, is_primary_key=True
        )
        create_test_attribute(
            session, clsi.id, name=f"campo_{i}_1", position=1, is_primary_key=False
        )
        create_test_attribute(
            session, clsi.id, name=f"campo_{i}_2", position=2, is_primary_key=False
        )
    session.commit()

    queries_case_b = []

    def callback_b(conn, cursor, statement, parameters, context, executemany):
        queries_case_b.append(statement)

    event.listen(test_engine, "before_cursor_execute", callback_b)
    try:
        resp_b = client.get(f"/api/projects/{project_id}/diagram")
        assert resp_b.status_code == 200
        assert len(resp_b.json()["classes"]) == 6
    finally:
        event.remove(test_engine, "before_cursor_execute", callback_b)

    count_b = len(queries_case_b)

    # La cantidad de consultas a la base de datos debe ser idéntica independientemente de N
    assert count_a > 0
    assert count_a == count_b


def test_get_diagram_snapshot_attribute_ordering_and_types(
    client: TestClient,
    session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que los atributos de cada clase se devuelven estrictamente ordenados por position ascendente con todos los tipos de datos soportados."""
    app.dependency_overrides[get_current_user] = lambda: owner_user
    project_id = test_project.id

    cls = create_test_class(session, project_id, name="EntidadCompleta", position_x=50.0, position_y=50.0)
    # Insertar en orden no secuencial para garantizar que el reader ordena por position
    create_test_attribute(session, cls.id, name="fecha_creacion", data_type="TIMESTAMP", position=6, is_primary_key=False, is_nullable=False)
    create_test_attribute(session, cls.id, name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)
    create_test_attribute(session, cls.id, name="activo", data_type="BOOLEAN", position=4, is_primary_key=False, is_nullable=False)
    create_test_attribute(session, cls.id, name="codigo", data_type="TEXT", position=1, is_primary_key=False, is_nullable=True)
    create_test_attribute(session, cls.id, name="nacimiento", data_type="DATE", position=5, is_primary_key=False, is_nullable=True)
    create_test_attribute(session, cls.id, name="cantidad", data_type="INTEGER", position=2, is_primary_key=False, is_nullable=False)
    create_test_attribute(session, cls.id, name="precio", data_type="DECIMAL", position=3, is_primary_key=False, is_nullable=True)
    create_test_attribute(session, cls.id, name="sin_tipo", data_type=None, position=7, is_primary_key=False, is_nullable=True)
    session.commit()

    resp = client.get(f"/api/projects/{project_id}/diagram")
    assert resp.status_code == 200
    classes = resp.json()["classes"]
    assert len(classes) == 1
    attrs = classes[0]["attributes"]
    assert len(attrs) == 8

    # Verificar orden estricto de posiciones 0 a 7
    assert [a["position"] for a in attrs] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert attrs[0]["name"] == "id"
    assert attrs[0]["data_type"] == "UUID"
    assert attrs[0]["is_primary_key"] is True
    assert attrs[0]["is_nullable"] is False

    assert attrs[1]["name"] == "codigo"
    assert attrs[1]["data_type"] == "TEXT"
    assert attrs[1]["is_primary_key"] is False
    assert attrs[1]["is_nullable"] is True

    assert attrs[2]["name"] == "cantidad"
    assert attrs[2]["data_type"] == "INTEGER"

    assert attrs[3]["name"] == "precio"
    assert attrs[3]["data_type"] == "DECIMAL"

    assert attrs[4]["name"] == "activo"
    assert attrs[4]["data_type"] == "BOOLEAN"

    assert attrs[5]["name"] == "nacimiento"
    assert attrs[5]["data_type"] == "DATE"

    assert attrs[6]["name"] == "fecha_creacion"
    assert attrs[6]["data_type"] == "TIMESTAMP"

    assert attrs[7]["name"] == "sin_tipo"
    assert attrs[7]["data_type"] is None
    assert attrs[7]["is_nullable"] is True

