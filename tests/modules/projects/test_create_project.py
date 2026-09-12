import uuid


def test_create_project_without_body(client):
    response = client.post("/api/projects")
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    project_id = uuid.UUID(data["id"])
    assert project_id is not None

    # Verificar que aparece en el listado con nombre por defecto
    list_response = client.get("/api/projects")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(project_id)
    assert items[0]["name"] == "Nuevo proyecto"
    assert items[0]["is_owner"] is True
