import uuid
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_delete_class_cascades_relations_with_single_commit():
    from app.modules.diagram.application.use_cases.diagram_class.delete_diagram_class import (
        DeleteDiagramClassCommand,
        DeleteDiagramClassUseCase,
    )

    class_id = uuid.uuid4()
    relation = MagicMock(id=uuid.uuid4())
    diagram_class = MagicMock(id=class_id, project_id=uuid.uuid4())
    classes = MagicMock()
    classes.find_by_id.side_effect = [diagram_class, diagram_class]
    relations = MagicMock()
    relations.list_by_class_id.return_value = [relation]
    attributes = MagicMock()
    attributes.list_by_class_id.return_value = []
    relation_deleter = MagicMock()
    uow = MagicMock()
    use_case = DeleteDiagramClassUseCase(
        access_policy=MagicMock(),
        diagram_class_repository=classes,
        diagram_relation_repository=relations,
        diagram_attribute_repository=attributes,
        delete_diagram_relation_use_case=relation_deleter,
        uow=uow,
    )

    use_case.execute(DeleteDiagramClassCommand(class_id, "user-1"))

    relation_deleter.execute.assert_called_once()
    assert relation_deleter.execute.call_args.kwargs == {"commit_transaction": False}
    classes.delete.assert_called_once_with(class_id)
    uow.commit.assert_called_once_with()


def test_delete_class_rolls_back_when_cascade_fails():
    from app.modules.diagram.application.use_cases.diagram_class.delete_diagram_class import (
        DeleteDiagramClassCommand,
        DeleteDiagramClassUseCase,
    )

    class_id = uuid.uuid4()
    diagram_class = MagicMock(id=class_id, project_id=uuid.uuid4())
    classes = MagicMock()
    classes.find_by_id.return_value = diagram_class
    relations = MagicMock()
    relations.list_by_class_id.return_value = []
    attributes = MagicMock()
    attributes.list_by_class_id.return_value = []
    classes.delete.side_effect = RuntimeError("cascade failed")
    uow = MagicMock()
    use_case = DeleteDiagramClassUseCase(
        access_policy=MagicMock(),
        diagram_class_repository=classes,
        diagram_relation_repository=relations,
        diagram_attribute_repository=attributes,
        delete_diagram_relation_use_case=MagicMock(),
        uow=uow,
    )

    try:
        use_case.execute(DeleteDiagramClassCommand(class_id, "user-1"))
        raise AssertionError("Expected cascade failure")
    except RuntimeError as error:
        assert str(error) == "cascade failed"

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_delete_class_rolls_back_when_cascade_fails():
    from app.modules.diagram.application.use_cases.diagram_class.delete_diagram_class import (
        DeleteDiagramClassCommand,
        DeleteDiagramClassUseCase,
    )

    class_id = uuid.uuid4()
    diagram_class = MagicMock(id=class_id, project_id=uuid.uuid4())
    classes = MagicMock()
    classes.find_by_id.return_value = diagram_class
    relations = MagicMock()
    relations.list_by_class_id.return_value = []
    attributes = MagicMock()
    attributes.list_by_class_id.return_value = []
    classes.delete.side_effect = RuntimeError("cascade failed")
    uow = MagicMock()
    use_case = DeleteDiagramClassUseCase(
        access_policy=MagicMock(),
        diagram_class_repository=classes,
        diagram_relation_repository=relations,
        diagram_attribute_repository=attributes,
        delete_diagram_relation_use_case=MagicMock(),
        uow=uow,
    )

    try:
        use_case.execute(DeleteDiagramClassCommand(class_id, "user-1"))
        raise AssertionError("Expected cascade failure")
    except RuntimeError as error:
        assert str(error) == "cascade failed"

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_delete_diagram_class(
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
    class_id_a = str(uuid.uuid4())
    class_id_b = str(uuid.uuid4())

    app.dependency_overrides[get_current_user] = lambda: owner_user

    # 1. Crear dos clases base
    resp_create_a = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_a,
            "name": "ClaseA",
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
    assert resp_create_a.status_code == 201

    # Crear atributo secundario en ClaseA para verificar eliminación en cascada
    attr_sec_id = str(uuid.uuid4())
    resp_attr_a = client.post(
        f"/api/diagram/classes/{class_id_a}/attributes",
        json={
            "id": attr_sec_id,
            "name": "descripcion",
            "position": 1,
        },
    )
    assert resp_attr_a.status_code == 201

    resp_create_b = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_b,
            "name": "ClaseB",
            "position_x": 300.0,
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
    assert resp_create_b.status_code == 201

    # 2. Colaborador con rol READER intenta eliminar ClaseA -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: reader_user
    resp_delete_reader = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_reader.status_code == 403

    # 3. Usuario no miembro (stranger) intenta eliminar ClaseA -> 404
    app.dependency_overrides[get_current_user] = lambda: stranger_user
    resp_delete_stranger = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_stranger.status_code == 404

    # 4. Miembro baneado o removido intenta eliminar -> 404
    app.dependency_overrides[get_current_user] = lambda: banned_user
    resp_delete_banned = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_banned.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: removed_user
    resp_delete_removed = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_removed.status_code == 404

    # 5. Colaborador con rol EDITOR elimina ClaseA -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: editor_user
    resp_delete_editor = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_delete_editor.status_code == 204

    # Verificar que ClaseA fue eliminada físicamente y solo queda ClaseB
    resp_list_after_a = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list_after_a.status_code == 200
    classes_after_a = resp_list_after_a.json()["classes"]
    assert len(classes_after_a) == 1
    assert classes_after_a[0]["id"] == class_id_b

    # Verificar que los atributos de ClaseA fueron eliminados en cascada
    resp_attr_after_del = client.patch(
        f"/api/diagram/attributes/{attr_sec_id}",
        json={"name": "nuevo_nombre"},
    )
    assert resp_attr_after_del.status_code == 404

    # 6. Reintento idempotente de eliminación ya confirmada -> 204 No Content
    resp_retry_delete = client.delete(f"/api/diagram/classes/{class_id_a}")
    assert resp_retry_delete.status_code == 204

    # 7. Propietario elimina ClaseB (eliminación múltiple de clases desde llamadas individuales) -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: owner_user
    resp_delete_b = client.delete(f"/api/diagram/classes/{class_id_b}")
    assert resp_delete_b.status_code == 204

    # Verificar que el lienzo quedó completamente vacío
    resp_list_empty = client.get(f"/api/projects/{project_id}/diagram")
    assert resp_list_empty.status_code == 200
    assert len(resp_list_empty.json()["classes"]) == 0
