import io
import zipfile
import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_generate_spring_boot_endpoint(client: TestClient, session: Session):
    owner_id = "user_test_1"

    # Crear proyecto para el usuario autenticado por defecto (user_test_1)
    project = ProjectModel(
        id=uuid.uuid4(),
        name="Sistema Ventas",
        description="Proyecto de prueba para generador",
        owner_id=owner_id,
    )
    session.add(project)
    session.commit()

    # Crear clase a través del API oficial de diagramas
    class_id = str(uuid.uuid4())
    pk_id = str(uuid.uuid4())
    payload = {
        "id": class_id,
        "name": "Cliente",
        "position_x": 100.0,
        "position_y": 150.0,
        "primary_attribute": {
            "id": pk_id,
            "name": "id",
            "data_type": "UUID",
            "position": 0,
            "is_primary_key": True,
            "is_nullable": False,
        },
    }
    resp_class = client.post(f"/api/projects/{project.id}/diagram/classes", json=payload)
    assert resp_class.status_code in (200, 201, 204)

    # La clase ya tiene su atributo primario (id) asignado.
    # Llamar al endpoint de generación de Spring Boot
    response = client.post(f"/api/code-generation/projects/{project.id}/spring-boot")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in response.headers["content-disposition"]

    # Verificar contenido del ZIP
    zip_bytes = response.content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
        assert any("Cliente.java" in n for n in names)
        assert any("ClienteController.java" in n for n in names)
        assert any("ClienteService.java" in n for n in names)
        assert any("ClienteRepository.java" in n for n in names)
        assert any("docker-compose.yml" in n for n in names)
        assert any("Dockerfile" in n for n in names)
        assert any("pom.xml" in n for n in names)
