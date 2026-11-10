import uuid
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.exceptions import InvalidDiagramAuditLogException
from app.modules.diagram.infrastructure.persistence.models.diagram_audit_log_model import (
    DiagramAuditLogModel,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_audit_log_repository import (
    SQLModelDiagramAuditLogRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


def test_audit_domain_entity_invariants():
    """Valida que la entidad DiagramAuditLog aplique sus invariantes estrictas."""
    project_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    # 1. user_id vacío
    with pytest.raises(InvalidDiagramAuditLogException):
        DiagramAuditLog.record(
            project_id=project_id,
            user_id="  ",
            user_name="Usuario",
            actor_type=DiagramAuditActorType.USER,
            entity_type=DiagramAuditEntityType.CLASS,
            entity_id=entity_id,
            entity_name="Test",
            action=DiagramAuditAction.CREATE,
            use_case="CREATE_CLASS",
            summary="Creación",
            payload_after={"id": str(entity_id)},
        )

    # 2. entity_name vacío
    with pytest.raises(InvalidDiagramAuditLogException):
        DiagramAuditLog.record(
            project_id=project_id,
            user_id="usr-1",
            user_name="Usuario",
            actor_type=DiagramAuditActorType.USER,
            entity_type=DiagramAuditEntityType.CLASS,
            entity_id=entity_id,
            entity_name="  ",
            action=DiagramAuditAction.CREATE,
            use_case="CREATE_CLASS",
            summary="Creación",
            payload_after={"id": str(entity_id)},
        )

    # 3. CREATE sin payload_after
    with pytest.raises(InvalidDiagramAuditLogException):
        DiagramAuditLog.record(
            project_id=project_id,
            user_id="usr-1",
            user_name="Usuario",
            actor_type=DiagramAuditActorType.USER,
            entity_type=DiagramAuditEntityType.CLASS,
            entity_id=entity_id,
            entity_name="Test",
            action=DiagramAuditAction.CREATE,
            use_case="CREATE_CLASS",
            summary="Creación",
            payload_after=None,
        )

    # 4. DELETE sin payload_before
    with pytest.raises(InvalidDiagramAuditLogException):
        DiagramAuditLog.record(
            project_id=project_id,
            user_id="usr-1",
            user_name="Usuario",
            actor_type=DiagramAuditActorType.USER,
            entity_type=DiagramAuditEntityType.CLASS,
            entity_id=entity_id,
            entity_name="Test",
            action=DiagramAuditAction.DELETE,
            use_case="DELETE_CLASS",
            summary="Eliminación",
            payload_before=None,
        )

    # 5. UPDATE sin payload_before o payload_after
    with pytest.raises(InvalidDiagramAuditLogException):
        DiagramAuditLog.record(
            project_id=project_id,
            user_id="usr-1",
            user_name="Usuario",
            actor_type=DiagramAuditActorType.USER,
            entity_type=DiagramAuditEntityType.CLASS,
            entity_id=entity_id,
            entity_name="Test",
            action=DiagramAuditAction.UPDATE,
            use_case="RENAME_CLASS",
            summary="Renombrado",
            payload_before={"name": "Viejo"},
            payload_after=None,
        )


def test_us1_audit_log_and_visual_movements_exclusion(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que los 9 casos de uso semánticos queden auditados y los movimientos visuales excluidos."""
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user
    repo = SQLModelDiagramAuditLogRepository(session)

    # 1. CREATE_CLASS
    class_id_1 = str(uuid.uuid4())
    pk_id_1 = str(uuid.uuid4())
    resp = client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_1,
            "name": "Producto",
            "position_x": 100.0,
            "position_y": 100.0,
            "primary_attribute": {
                "id": pk_id_1,
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
        },
    )
    assert resp.status_code == 201



    logs = repo.list_by_project(project_id)
    assert len(logs) == 1
    log_create_cls = logs[0]
    assert log_create_cls.use_case == "CREATE_CLASS"
    assert log_create_cls.action == DiagramAuditAction.CREATE
    assert log_create_cls.entity_type == DiagramAuditEntityType.CLASS
    assert str(log_create_cls.entity_id) == class_id_1
    assert log_create_cls.entity_name == "Producto"
    assert log_create_cls.payload_before is None
    assert log_create_cls.payload_after is not None
    assert log_create_cls.payload_after["name"] == "Producto"
    assert len(log_create_cls.payload_after["attributes"]) == 1

    # 2. RENAME_CLASS
    resp = client.patch(
        f"/api/diagram/classes/{class_id_1}/name",
        json={"name": "Articulo"},
    )
    assert resp.status_code == 204

    logs = repo.list_by_project(project_id)
    assert len(logs) == 2
    log_rename_cls = logs[0]
    assert log_rename_cls.use_case == "RENAME_CLASS"
    assert log_rename_cls.action == DiagramAuditAction.UPDATE
    assert log_rename_cls.entity_name == "Articulo"
    assert log_rename_cls.payload_before["name"] == "Producto"
    assert log_rename_cls.payload_after["name"] == "Articulo"

    # 3. EXCLUSIÓN: MOVE_CLASS no debe crear entrada de bitácora
    resp = client.patch(
        f"/api/diagram/classes/{class_id_1}/position",
        json={"position_x": 300.0, "position_y": 400.0},
    )
    assert resp.status_code == 204
    logs_after_move = repo.list_by_project(project_id)
    assert len(logs_after_move) == 2, "MOVE_CLASS no debe registrar bitácora"


    # 4. CREATE_ATTRIBUTE
    attr_id_1 = str(uuid.uuid4())
    resp = client.post(
        f"/api/diagram/classes/{class_id_1}/attributes",
        json={
            "id": attr_id_1,
            "name": "precio",
            "position": 1,
        },
    )
    assert resp.status_code == 201



    logs = repo.list_by_project(project_id)
    assert len(logs) == 3
    log_create_attr = logs[0]
    assert log_create_attr.use_case == "CREATE_ATTRIBUTE"
    assert log_create_attr.action == DiagramAuditAction.CREATE
    assert log_create_attr.entity_type == DiagramAuditEntityType.ATTRIBUTE
    assert str(log_create_attr.entity_id) == attr_id_1
    assert log_create_attr.entity_name == "precio"
    assert str(log_create_attr.parent_class_id) == class_id_1
    assert log_create_attr.parent_class_name == "Articulo"
    assert log_create_attr.payload_before is None
    assert log_create_attr.payload_after["name"] == "precio"

    # 5. UPDATE_ATTRIBUTE
    resp = client.patch(
        f"/api/diagram/attributes/{attr_id_1}",
        json={"name": "precio_unitario", "data_type": "DECIMAL", "is_nullable": False},
    )
    assert resp.status_code == 204


    logs = repo.list_by_project(project_id)
    assert len(logs) == 4
    log_update_attr = logs[0]
    assert log_update_attr.use_case == "UPDATE_ATTRIBUTE"
    assert log_update_attr.action == DiagramAuditAction.UPDATE
    assert log_update_attr.payload_before["name"] == "precio"
    assert log_update_attr.payload_after["name"] == "precio_unitario"
    assert log_update_attr.payload_after["data_type"] == "DECIMAL"

    # 6. EXCLUSIÓN: REPOSITION_ATTRIBUTE no debe registrar bitácora
    # Creamos un segundo atributo para poder reposicionar
    attr_id_2 = str(uuid.uuid4())
    resp_create_attr2 = client.post(
        f"/api/diagram/classes/{class_id_1}/attributes",
        json={
            "id": attr_id_2,
            "name": "stock",
            "position": 2,
        },
    )
    assert resp_create_attr2.status_code == 201
    count_before_reposition = len(repo.list_by_project(project_id))
    resp = client.patch(
        f"/api/diagram/attributes/{attr_id_2}/position",
        json={"position": 1},
    )
    assert resp.status_code == 204

    assert len(repo.list_by_project(project_id)) == count_before_reposition, (
        "REPOSITION_ATTRIBUTE no debe registrar bitácora"
    )

    # 7. DELETE_ATTRIBUTE
    resp = client.delete(
        f"/api/diagram/attributes/{attr_id_2}"
    )
    assert resp.status_code == 204



    logs = repo.list_by_project(project_id)
    log_delete_attr = logs[0]
    assert log_delete_attr.use_case == "DELETE_ATTRIBUTE"
    assert log_delete_attr.action == DiagramAuditAction.DELETE
    assert str(log_delete_attr.entity_id) == attr_id_2
    assert log_delete_attr.payload_before["name"] == "stock"
    assert log_delete_attr.payload_after is None

    # 8. CREATE_RELATION
    # Creamos clase destino
    class_id_2 = str(uuid.uuid4())
    pk_id_2 = str(uuid.uuid4())
    client.post(
        f"/api/projects/{project_id}/diagram/classes",
        json={
            "id": class_id_2,
            "name": "Categoria",
            "position_x": 500.0,
            "position_y": 100.0,
            "primary_attribute": {"id": pk_id_2, "name": "id"},
        },
    )
    rel_id_1 = str(uuid.uuid4())
    fk_id_1 = str(uuid.uuid4())
    resp = client.post(
        f"/api/projects/{project_id}/diagram/relations",
        json={
            "id": rel_id_1,
            "name": "pertenece",
            "relation_type": "ASSOCIATION",
            "source": {
                "class_id": class_id_2,
                "handle": "LEFT_CENTER",
                "cardinality": "1",
            },
            "target": {
                "class_id": class_id_1,
                "handle": "RIGHT_CENTER",
                "cardinality": "0..*",
            },
            "materialization": {
                "strategy": "FOREIGN_KEY",
                "foreign_attributes": [
                    {
                        "id": fk_id_1,
                        "class_id": class_id_1,
                        "name": "categoria_id",
                        "data_type": "UUID",
                        "position": 2,
                        "is_primary_key": False,
                        "is_nullable": False,
                        "is_foreign_key": True,
                        "referenced_class_id": class_id_2,
                        "relation_id": rel_id_1,
                    }
                ],
            },
        },
    )
    assert resp.status_code == 201





    logs = repo.list_by_project(project_id)
    log_create_rel = logs[0]
    assert log_create_rel.use_case == "CREATE_RELATION"
    assert log_create_rel.action == DiagramAuditAction.CREATE
    assert log_create_rel.entity_type == DiagramAuditEntityType.RELATION
    assert str(log_create_rel.entity_id) == rel_id_1
    assert log_create_rel.payload_after["source_class_name"] == "Categoria"
    assert log_create_rel.payload_after["target_class_name"] == "Articulo"

    # 9. RENAME_RELATION
    resp = client.patch(
        f"/api/diagram/relations/{rel_id_1}/name",
        json={"name": "clasificado_en"},
    )
    assert resp.status_code == 204



    logs = repo.list_by_project(project_id)
    log_rename_rel = logs[0]
    assert log_rename_rel.use_case == "RENAME_RELATION"
    assert log_rename_rel.action == DiagramAuditAction.UPDATE
    assert log_rename_rel.entity_name == "clasificado_en"
    assert log_rename_rel.payload_before["name"] == "pertenece"
    assert log_rename_rel.payload_after["name"] == "clasificado_en"

    # 10. DELETE_RELATION
    resp = client.delete(f"/api/diagram/relations/{rel_id_1}")
    assert resp.status_code == 204

    logs = repo.list_by_project(project_id)
    log_delete_rel = logs[0]
    assert log_delete_rel.use_case == "DELETE_RELATION"
    assert log_delete_rel.action == DiagramAuditAction.DELETE
    assert log_delete_rel.payload_before["name"] == "clasificado_en"
    assert log_delete_rel.payload_after is None

    # 11. DELETE_CLASS
    resp = client.delete(f"/api/diagram/classes/{class_id_1}")
    assert resp.status_code == 204


    logs = repo.list_by_project(project_id)
    log_delete_cls = logs[0]
    assert log_delete_cls.use_case == "DELETE_CLASS"
    assert log_delete_cls.action == DiagramAuditAction.DELETE
    assert str(log_delete_cls.entity_id) == class_id_1
    assert log_delete_cls.payload_before["name"] == "Articulo"
    assert log_delete_cls.payload_after is None


def test_us2_assistant_actions_attributed_to_requesting_user(
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que las mutaciones ejecutadas por el asistente de IA lleven actor_type=ASSISTANT y user_id del usuario."""
    from app.modules.diagram.application.services.diagram_access_policy import (
        DiagramAccessPolicy,
    )
    from app.modules.diagram.application.use_cases.diagram_class.create_diagram_class import (
        CreateDiagramClassCommand,
        CreateDiagramClassUseCase,
    )
    from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
        SQLModelDiagramAttributeRepository,
    )
    from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
        SQLModelDiagramClassRepository,
    )
    from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
        SQLModelProjectMemberRepository,
    )

    from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
        SQLModelProjectRepository,
    )
    from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
    from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork

    project_id = test_project.id
    uow = SqlModelUnitOfWork(session, InMemoryEventBus())

    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    cls_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    use_case = CreateDiagramClassUseCase(policy, cls_repo, attr_repo, uow)


    class_id = uuid.uuid4()
    pk_id = uuid.uuid4()
    cmd = CreateDiagramClassCommand(
        id=class_id,
        project_id=project_id,
        user_id=owner_user.user_id,
        name="ClaseAsistente",
        position_x=150.0,
        position_y=250.0,
        primary_attribute_id=pk_id,
        event_sender_id="assistant",
    )

    use_case.execute(cmd)

    repo = SQLModelDiagramAuditLogRepository(session)
    logs = repo.list_by_project(project_id, entity_id=class_id)
    assert len(logs) == 1
    log = logs[0]
    assert log.actor_type == DiagramAuditActorType.ASSISTANT
    assert log.user_id == owner_user.user_id
    assert log.entity_name == "ClaseAsistente"


def test_us3_repository_filters_and_queries(
    session: Session,
    test_project: ProjectModel,
):
    """Verifica las capacidades de filtrado y consulta histórica por colaborador, fechas y entidad."""
    project_id = test_project.id
    repo = SQLModelDiagramAuditLogRepository(session)

    # Crear usuario BetterAuth para búsqueda por nombre
    juan = BetterAuthUser(id="usr_juan", name="Juan Perez", email="juan@perez.com")
    maria = BetterAuthUser(id="usr_maria", name="Maria Gomez", email="maria@gomez.com")
    session.add(juan)
    session.add(maria)
    session.commit()

    now = datetime.now(timezone.utc)
    t1 = now - timedelta(days=5)
    t2 = now - timedelta(days=2)
    t3 = now - timedelta(hours=1)

    class_id = uuid.uuid4()
    attr_id = uuid.uuid4()
    rel_id = uuid.uuid4()

    # Log 1: Juan crea clase en t1
    log1 = DiagramAuditLog.record(
        project_id=project_id,
        user_id="usr_juan",
        user_name="Juan Perez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Orden",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Juan creó la clase 'Orden'",
        payload_after={"id": str(class_id), "name": "Orden"},
        created_date=t1,
    )
    repo.save(log1)

    # Log 2: Maria agrega atributo en t2
    log2 = DiagramAuditLog.record(
        project_id=project_id,
        user_id="usr_maria",
        user_name="Maria Gomez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.ATTRIBUTE,
        entity_id=attr_id,
        entity_name="total",
        parent_class_id=class_id,
        parent_class_name="Orden",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_ATTRIBUTE",
        summary="Maria agregó 'total'",
        payload_after={"id": str(attr_id), "name": "total"},
        created_date=t2,
    )
    repo.save(log2)

    # Log 3: Juan mediante Asistente en t3 crea relación
    log3 = DiagramAuditLog.record(
        project_id=project_id,
        user_id="usr_juan",
        user_name="Juan Perez",
        actor_type=DiagramAuditActorType.ASSISTANT,
        entity_type=DiagramAuditEntityType.RELATION,
        entity_id=rel_id,
        entity_name="detalle",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_RELATION",
        summary="Asistente creó 'detalle'",
        payload_after={"id": str(rel_id), "name": "detalle"},
        created_date=t3,
    )
    repo.save(log3)
    session.commit()

    # 1. Consulta total (orden cronológico descendente: log3, log2, log1)
    all_logs = repo.list_by_project(project_id)
    assert len(all_logs) == 3
    assert all_logs[0].id == log3.id
    assert all_logs[1].id == log2.id
    assert all_logs[2].id == log1.id

    # 2. Filtrar por user_search "juan" (case-insensitive)
    juan_logs = repo.list_by_project(project_id, user_search="juan")
    assert len(juan_logs) == 2
    assert all(l.user_id == "usr_juan" for l in juan_logs)

    # 3. Filtrar por actor_type ASSISTANT
    assistant_logs = repo.list_by_project(
        project_id, actor_type=DiagramAuditActorType.ASSISTANT
    )
    assert len(assistant_logs) == 1
    assert assistant_logs[0].id == log3.id

    # 4. Filtrar por parent_class_id
    attr_logs = repo.list_by_project(project_id, parent_class_id=class_id)
    assert len(attr_logs) == 1
    assert attr_logs[0].id == log2.id

    # 5. Filtrar por ventana temporal (desde hace 3 días hasta hace 30 min)
    temporal_logs = repo.list_by_project(
        project_id,
        since=now - timedelta(days=3),
        until=now - timedelta(minutes=30),
    )
    assert len(temporal_logs) == 2
    assert {l.id for l in temporal_logs} == {log2.id, log3.id}

    # 6. Paginación
    page1 = repo.list_by_project(project_id, limit=2, offset=0)
    page2 = repo.list_by_project(project_id, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert page1[0].id == log3.id
    assert page1[1].id == log2.id
    assert page2[0].id == log1.id


def test_us1_idempotent_no_ops_do_not_create_duplicate_audit_logs(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Verifica que reintentos idempotentes y actualizaciones sin cambios no emitan entradas duplicadas."""
    project_id = test_project.id
    app.dependency_overrides[get_current_user] = lambda: owner_user
    repo = SQLModelDiagramAuditLogRepository(session)

    class_id = str(uuid.uuid4())
    pk_id = str(uuid.uuid4())
    payload = {
        "id": class_id,
        "name": "Cliente",
        "position_x": 100.0,
        "position_y": 100.0,
        "primary_attribute": {
            "id": pk_id,
            "name": "id",
            "data_type": "UUID",
            "position": 0,
            "is_primary_key": True,
            "is_nullable": False,
        },
    }

    # Creación inicial -> 201 Created y 1 entrada de bitácora
    resp1 = client.post(f"/api/projects/{project_id}/diagram/classes", json=payload)
    assert resp1.status_code == 201
    assert len(repo.list_by_project(project_id)) == 1

    # Reintento exacto -> 204 No Content y la bitácora NO aumenta
    resp2 = client.post(f"/api/projects/{project_id}/diagram/classes", json=payload)
    assert resp2.status_code == 204
    assert len(repo.list_by_project(project_id)) == 1

    # Renombrar con el mismo nombre -> 204 No Content y la bitácora NO aumenta
    resp3 = client.patch(
        f"/api/diagram/classes/{class_id}/name",
        json={"name": "Cliente"},
    )
    assert resp3.status_code == 204
    assert len(repo.list_by_project(project_id)) == 1

