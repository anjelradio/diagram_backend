from uuid import uuid4
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app


def test_delete_project_lifecycle(client, session: Session):
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

    # 3. Usuario 2 se une al proyecto
    user2 = AuthUser(user_id="user_test_2", email="dos@test.com")
    app.dependency_overrides[get_current_user] = lambda: user2

    resp_join = client.post("/api/projects/join", json={"code": code})
    assert resp_join.status_code == 200


    # Usuario 2 lo ve en su lista
    resp_list2 = client.get("/api/projects")
    assert len(resp_list2.json()["items"]) == 1

    # 4. Usuario 2 intenta eliminar el proyecto -> 403 Forbidden
    resp_forbidden = client.delete(f"/api/projects/{project_id}")
    assert resp_forbidden.status_code == 403

    # 5. Usuario 1 elimina el proyecto -> 204 No Content
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_delete = client.delete(f"/api/projects/{project_id}")
    assert resp_delete.status_code == 204

    # 6. Desaparición para propietario
    resp_list1_after = client.get("/api/projects")
    assert len(resp_list1_after.json()["items"]) == 0

    # 7. Desaparición para participante
    app.dependency_overrides[get_current_user] = lambda: user2
    resp_list2_after = client.get("/api/projects")
    assert len(resp_list2_after.json()["items"]) == 0

    # 8. Usuario 3 intenta unirse con la invitación del proyecto eliminado -> 404
    user3 = AuthUser(user_id="user_test_3", email="tres@test.com")
    app.dependency_overrides[get_current_user] = lambda: user3
    resp_join_deleted = client.post("/api/projects/join", json={"code": code})
    assert resp_join_deleted.status_code == 404

    # 9. Intentar eliminar proyecto ya eliminado o inexistente -> 404
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_delete_again = client.delete(f"/api/projects/{project_id}")
    assert resp_delete_again.status_code == 404
