import uuid
from sqlmodel import Session

from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_list_projects_empty(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert data == {"items": []}


def test_list_projects_own_and_shared(client, session: Session):
    # 1. Proyecto propio activo
    p1 = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto Propio",
        description="Mi descripción",
    )
    # 2. Proyecto propio eliminado
    p_deleted = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto Eliminado",
    )
    p_deleted.soft_delete()

    # 3. Proyecto ajeno compartido activo
    p2 = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_2",
        name="Proyecto Compartido Activo",
    )
    member_active = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=p2.id,
        user_id="user_test_1",
        role=ProjectMemberRole.READER.value,
        status=ProjectMemberStatus.ACTIVE.value,
    )

    # 4. Proyecto ajeno compartido REMOVIDO
    p3 = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_2",
        name="Proyecto Compartido Removido",
    )
    member_removed = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=p3.id,
        user_id="user_test_1",
        role=ProjectMemberRole.READER.value,
        status=ProjectMemberStatus.REMOVED.value,
    )

    # 5. Proyecto ajeno compartido BANEADO
    p4 = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_2",
        name="Proyecto Compartido Baneado",
    )
    member_banned = ProjectMemberModel(
        id=uuid.uuid4(),
        project_id=p4.id,
        user_id="user_test_1",
        role=ProjectMemberRole.READER.value,
        status=ProjectMemberStatus.BANNED.value,
    )

    session.add_all([p1, p_deleted, p2, p3, p4])
    session.flush()
    session.add_all([member_active, member_removed, member_banned])
    session.commit()

    response = client.get("/api/projects")
    assert response.status_code == 200
    items = response.json()["items"]

    assert len(items) == 2
    item_names = {i["name"]: i for i in items}

    assert "Proyecto Propio" in item_names
    assert item_names["Proyecto Propio"]["is_owner"] is True
    assert "modified_date" in item_names["Proyecto Propio"]

    assert "Proyecto Compartido Activo" in item_names
    assert item_names["Proyecto Compartido Activo"]["is_owner"] is False
    assert "modified_date" in item_names["Proyecto Compartido Activo"]

    assert "Proyecto Eliminado" not in item_names
    assert "Proyecto Compartido Removido" not in item_names
    assert "Proyecto Compartido Baneado" not in item_names


def test_list_projects_order_by_modified_date_desc(client, session: Session):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    p_old = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto Antiguo",
        modified_date=now - timedelta(days=5),
    )
    p_recent = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto Reciente",
        modified_date=now - timedelta(minutes=10),
    )
    p_newest = ProjectModel(
        id=uuid.uuid4(),
        owner_id="user_test_1",
        name="Proyecto Mas Nuevo",
        modified_date=now,
    )

    session.add_all([p_old, p_recent, p_newest])
    session.commit()

    response = client.get("/api/projects")
    assert response.status_code == 200
    items = response.json()["items"]

    assert len(items) >= 3
    names = [i["name"] for i in items[:3]]
    assert names == ["Proyecto Mas Nuevo", "Proyecto Reciente", "Proyecto Antiguo"]

