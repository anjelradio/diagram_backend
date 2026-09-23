from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.persistence.models.invitation_model import (
    InvitationModel,
)
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)


def test_invitation_lifecycle_and_join(client, session: Session):
    # 1. Usuario 1 crea proyecto
    resp_create = client.post("/api/projects")
    assert resp_create.status_code == 201
    project_id = UUID(resp_create.json()["id"])

    # 2. Usuario 1 genera invitación
    resp_inv1 = client.post(f"/api/projects/{project_id}/invitations")
    assert resp_inv1.status_code == 201
    inv_data1 = resp_inv1.json()
    code1 = inv_data1["code"]
    assert len(code1) == 10
    assert code1.isalnum()

    # 3. Usuario 1 solicita invitación vigente de nuevo -> mismo código
    resp_inv2 = client.post(f"/api/projects/{project_id}/invitations")
    assert resp_inv2.status_code == 201
    assert resp_inv2.json()["code"] == code1

    # 4. Usuario 1 se une de forma idempotente a su propio proyecto -> 200 OK con project_id
    resp_self_join = client.post("/api/projects/join", json={"code": code1})
    assert resp_self_join.status_code == 200
    assert resp_self_join.json()["project_id"] == str(project_id)

    # 5. Cambiamos a Usuario 2
    user2 = AuthUser(user_id="user_test_2", email="dos@test.com")
    app.dependency_overrides[get_current_user] = lambda: user2

    # Usuario 2 se une al proyecto -> 200 OK con project_id
    resp_join = client.post("/api/projects/join", json={"code": code1})
    assert resp_join.status_code == 200
    assert resp_join.json()["project_id"] == str(project_id)

    # Usuario 2 ahora ve el proyecto en su lista con is_owner=False
    resp_list2 = client.get("/api/projects")
    assert resp_list2.status_code == 200
    items2 = resp_list2.json()["items"]
    assert len(items2) == 1
    assert items2[0]["id"] == str(project_id)
    assert items2[0]["is_owner"] is False

    # Usuario 2 intenta unirse de nuevo mientras está activo -> 200 OK idempotente con project_id
    resp_rejoin_active = client.post("/api/projects/join", json={"code": code1})
    assert resp_rejoin_active.status_code == 200
    assert resp_rejoin_active.json()["project_id"] == str(project_id)

    # 6. Simular remoción de Usuario 2
    stmt_member = select(ProjectMemberModel).where(
        ProjectMemberModel.project_id == project_id,
        ProjectMemberModel.user_id == "user_test_2",
    )
    member_record = session.exec(stmt_member).first()
    assert member_record is not None
    member_record.status = ProjectMemberStatus.REMOVED.value
    member_record.role = ProjectMemberRole.EDITOR.value
    session.add(member_record)
    session.commit()

    # Usuario 2 se une nuevamente -> se reactiva con rol READER y 200 OK con project_id
    resp_rejoin_removed = client.post("/api/projects/join", json={"code": code1})
    assert resp_rejoin_removed.status_code == 200
    assert resp_rejoin_removed.json()["project_id"] == str(project_id)

    session.refresh(member_record)
    assert member_record.status == ProjectMemberStatus.ACTIVE.value
    assert member_record.role == ProjectMemberRole.READER.value

    # 7. Simular bloqueo de Usuario 2
    member_record.status = ProjectMemberStatus.BANNED.value
    session.add(member_record)
    session.commit()

    # Usuario 2 intenta unirse con código -> 403 Forbidden
    resp_rejoin_banned = client.post("/api/projects/join", json={"code": code1})
    assert resp_rejoin_banned.status_code == 403

    # 8. Probar código vencido
    stmt_inv = select(InvitationModel).where(InvitationModel.code == code1)
    inv_record = session.exec(stmt_inv).first()
    inv_record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(inv_record)
    session.commit()

    # Usuario 2 intenta unirse con código vencido -> 404
    resp_expired_join = client.post("/api/projects/join", json={"code": code1})
    assert resp_expired_join.status_code == 404

    # Usuario 1 (propietario) renueva la invitación vencida
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        user_id="user_test_1", email="uno@test.com"
    )
    resp_renew = client.post(f"/api/projects/{project_id}/invitations")
    assert resp_renew.status_code == 201
    new_code = resp_renew.json()["code"]
    assert new_code != code1
