from uuid import uuid4
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app


def test_update_project_lifecycle(client, session: Session):
    # 1. Usuario 1 crea proyecto
    user1 = AuthUser(user_id="user_test_1", email="uno@test.com")
    app.dependency_overrides[get_current_user] = lambda: user1

    resp_create = client.post("/api/projects")
    assert resp_create.status_code == 201
    project_id = resp_create.json()["id"]

    # 2. Actualizar nombre y descripción como propietario
    resp_update = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Diagrama de Arquitectura", "description": "Sistema de pagos v2"},
    )
    assert resp_update.status_code == 204

    # Verificar cambios en el listado
    resp_list = client.get("/api/projects")
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    assert items[0]["name"] == "Diagrama de Arquitectura"
    assert items[0]["description"] == "Sistema de pagos v2"

    # 3. Usuario 2 intenta actualizar el proyecto -> 403 Forbidden
    user2 = AuthUser(user_id="user_test_2", email="dos@test.com")
    app.dependency_overrides[get_current_user] = lambda: user2

    resp_forbidden = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Intento no autorizado"},
    )
    assert resp_forbidden.status_code == 403

    # 4. Validar que el nombre no haya cambiado
    app.dependency_overrides[get_current_user] = lambda: user1
    resp_list_after = client.get("/api/projects")
    assert resp_list_after.json()["items"][0]["name"] == "Diagrama de Arquitectura"

    # 5. Validación de nombre vacío / espacios
    resp_invalid_empty = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "   "},
    )
    # Puede ser 422 (pydantic/domain)
    assert resp_invalid_empty.status_code in (400, 422)

    # 6. Validación de nombre mayor a 255 caracteres
    resp_too_long = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "a" * 256},
    )
    assert resp_too_long.status_code in (400, 422)

    # 7. Proyecto inexistente -> 404
    resp_not_found = client.patch(
        f"/api/projects/{uuid4()}",
        json={"name": "Proyecto Fantasma"},
    )
    assert resp_not_found.status_code == 404
