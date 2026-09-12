from uuid import UUID
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus


def test_manage_members_lifecycle(client, session: Session):
    # 1. Usuario 1 crea proyecto
    user1 = AuthUser(user_id="user_test_1", email="uno@test.com")
    app.dependency_overrides[get_current_user] = lambda: user1

    resp_create = client.post("/api/projects")
    assert resp_create.status_code == 201
    project_id = resp_create.json()["id"]

    # 2. Generar invitación
    resp_inv = client.post(f"/api/projects/{project_id}/invitations")
    assert resp_inv.status_code == 201
    code = resp_inv.json()["code"]

    # 3. Usuario 2 se une
    user2 = AuthUser(user_id="user_test_2", email="dos@test.com")
    app.dependency_overrides[get_current_user] = lambda: user2

    resp_join = client.post("/api/projects/join", json={"code": code})
    assert resp_join.status_code == 200


    # 4. Usuario 2 (no propietario) intenta listar miembros -> 403
    resp_list_forbidden = client.get(f"/api/projects/{project_id}/members")
    assert resp_list_forbidden.status_code == 403

    # 5. Usuario 1 (propietario) lista miembros
    app.dependency_overrides[get_current_user] = lambda: user1

    resp_members = client.get(f"/api/projects/{project_id}/members")
    assert resp_members.status_code == 200
    items = resp_members.json()["items"]
    assert len(items) == 1
    member = items[0]
    assert member["user_id"] == "user_test_2"
    assert member["role"] == ProjectMemberRole.READER.value
    assert member["status"] == ProjectMemberStatus.ACTIVE.value
    member_id = member["id"]

    # Intentar desbanear a un usuario que no está baneado -> 409 Conflict
    resp_unban_not_banned = client.post(f"/api/projects/{project_id}/members/{member_id}/unban")
    assert resp_unban_not_banned.status_code == 409

    # 6. Promover a EDITOR (sin body)
    resp_promote = client.post(f"/api/projects/{project_id}/members/{member_id}/promote")
    assert resp_promote.status_code == 204

    # Verificar que el rol se actualizó a EDITOR
    resp_members_after_role = client.get(f"/api/projects/{project_id}/members")
    assert resp_members_after_role.status_code == 200
    assert resp_members_after_role.json()["items"][0]["role"] == ProjectMemberRole.EDITOR.value

    # Degradar a READER (sin body)
    resp_demote = client.post(f"/api/projects/{project_id}/members/{member_id}/demote")
    assert resp_demote.status_code == 204

    # Verificar que el rol regresó a READER
    resp_members_demoted = client.get(f"/api/projects/{project_id}/members")
    assert resp_members_demoted.json()["items"][0]["role"] == ProjectMemberRole.READER.value

    # 7. Usuario 2 intenta promover o degradar -> 403
    app.dependency_overrides[get_current_user] = lambda: user2
    resp_promote_forbidden = client.post(f"/api/projects/{project_id}/members/{member_id}/promote")
    assert resp_promote_forbidden.status_code == 403
    resp_demote_forbidden = client.post(f"/api/projects/{project_id}/members/{member_id}/demote")
    assert resp_demote_forbidden.status_code == 403

    # 8. Usuario 1 remueve a Usuario 2 (sin body)
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_remove = client.post(f"/api/projects/{project_id}/members/{member_id}/remove")
    assert resp_remove.status_code == 204

    # Filtrar por ACTIVE -> 0 miembros
    resp_active = client.get(f"/api/projects/{project_id}/members?status_filter=ACTIVE")
    assert resp_active.status_code == 200
    assert len(resp_active.json()["items"]) == 0

    # Filtrar por REMOVED -> 1 miembro
    resp_removed = client.get(f"/api/projects/{project_id}/members?status_filter=REMOVED")
    assert resp_removed.status_code == 200
    assert len(resp_removed.json()["items"]) == 1

    # Usuario 2 no ve el proyecto en su lista
    app.dependency_overrides[get_current_user] = lambda: user2
    resp_list_user2 = client.get("/api/projects")
    assert len(resp_list_user2.json()["items"]) == 0

    # 9. Usuario 1 bloquea a Usuario 2 (sin body)
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_ban = client.post(f"/api/projects/{project_id}/members/{member_id}/ban")
    assert resp_ban.status_code == 204

    # Filtrar por BANNED -> 1 miembro
    resp_banned = client.get(f"/api/projects/{project_id}/members?status_filter=BANNED")
    assert resp_banned.status_code == 200
    assert len(resp_banned.json()["items"]) == 1

    # Intentar cambiar rol de usuario bloqueado -> 409 Conflict
    resp_promote_banned = client.post(f"/api/projects/{project_id}/members/{member_id}/promote")
    assert resp_promote_banned.status_code == 409

    # Usuario 2 intenta reingresar -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: user2
    resp_join_banned = client.post("/api/projects/join", json={"code": code})
    assert resp_join_banned.status_code == 403

    # 10. Usuario 1 desbanea a Usuario 2 (sin body)
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_unban = client.post(f"/api/projects/{project_id}/members/{member_id}/unban")
    assert resp_unban.status_code == 204

    # Verificar que el usuario ahora está ACTIVE
    resp_members_unbanned = client.get(f"/api/projects/{project_id}/members?status_filter=ACTIVE")
    assert resp_members_unbanned.status_code == 200
    assert len(resp_members_unbanned.json()["items"]) == 1

    # Usuario 2 ve de nuevo el proyecto en su listado
    app.dependency_overrides[get_current_user] = lambda: user2
    resp_list_user2_unbanned = client.get("/api/projects")
    assert len(resp_list_user2_unbanned.json()["items"]) == 1
