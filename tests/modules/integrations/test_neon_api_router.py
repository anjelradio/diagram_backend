from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.integrations.application.ports.providers.neon_integration_provider import (
    NeonIntegrationProvider,
    NeonProvisionedProject,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresColumn,
    CurrentPostgresSchema,
    CurrentPostgresTable,
)
from app.modules.integrations.domain.exceptions import NeonInvalidCredentialsException
from app.modules.integrations.infrastructure.api.dependencies import get_neon_provider
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


class FakeNeonApiProvider(NeonIntegrationProvider):
    def __init__(self) -> None:
        self.is_valid = True
        self.introspected_tables: dict[str, CurrentPostgresTable] = {}
        self.executed_ddls: list[str] = []

    def validate_api_key(self, api_key: str) -> tuple[bool, str | None]:
        if "invalid" in api_key:
            return False, "Invalid API key"
        return True, "test_user"

    def create_project_and_database(
        self, api_key: str, project_name: str
    ) -> NeonProvisionedProject:
        valid, _ = self.validate_api_key(api_key)
        if not valid:
            raise NeonInvalidCredentialsException()
        return NeonProvisionedProject(
            project_id=f"neon-proj-{uuid4().hex[:8]}",
            database_name="neondb",
            branch_id="br-main-1",
            console_url="https://console.neon.tech/app/projects/test",
            connection_uri="postgresql://user:pass@ep-test.neon.tech/neondb",
        )

    def introspect_database_schema(self, connection_uri: str) -> CurrentPostgresSchema:
        return CurrentPostgresSchema(tables=dict(self.introspected_tables))

    def execute_sql_migration(self, connection_uri: str, statements: list[str]) -> bool:
        self.executed_ddls.extend(statements)
        return True


@pytest.fixture
def fake_neon():
    provider = FakeNeonApiProvider()
    app.dependency_overrides[get_neon_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_neon_provider, None)


def test_neon_api_router_lifecycle(client: TestClient, session: Session, fake_neon: FakeNeonApiProvider):
    owner_id = "user_test_1"  # Default user in testclient
    project = ProjectModel(
        id=uuid4(),
        name="Inventory Pro",
        owner_id=owner_id,
    )
    session.add(project)
    session.commit()

    # 1. GET status inicial (sin API key)
    res_get = client.get(f"/api/projects/{project.id}/integrations/neon")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["has_api_key"] is False
    assert data_get["is_initialized"] is False
    assert data_get["neon_project_id"] is None

    # 2. PUT /config con API key inválida
    res_invalid = client.put(
        f"/api/projects/{project.id}/integrations/neon/config",
        json={"api_key": "napi_invalid_key"},
    )
    assert res_invalid.status_code == 400

    # 3. PUT /config con API key válida
    res_config = client.put(
        f"/api/projects/{project.id}/integrations/neon/config",
        json={"api_key": "napi_valid_key_123"},
    )
    assert res_config.status_code == 200
    data_config = res_config.json()
    assert data_config["has_api_key"] is True
    assert data_config["is_initialized"] is False

    # 4. POST /initialize sin clases -> 400 (empty diagram)
    res_init_empty = client.post(f"/api/projects/{project.id}/integrations/neon/initialize")
    assert res_init_empty.status_code == 400

    # 5. Agregar una clase con atributos en el diagrama
    cls = DiagramClassModel(
        project_id=project.id,
        name="Articulo",
        position_x=10,
        position_y=20,
    )
    session.add(cls)
    session.commit()
    session.refresh(cls)

    attr_id = DiagramAttributeModel(
        class_id=cls.id,
        name="id",
        data_type=DiagramAttributeDataType.UUID,
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    attr_nombre = DiagramAttributeModel(
        class_id=cls.id,
        name="nombre",
        data_type=DiagramAttributeDataType.TEXT,
        position=1,
        is_nullable=False,
    )
    session.add(attr_id)
    session.add(attr_nombre)
    session.commit()

    # 6. POST /initialize con diagrama poblado -> 201 Created
    res_init = client.post(f"/api/projects/{project.id}/integrations/neon/initialize")
    assert res_init.status_code == 201
    data_init = res_init.json()
    assert data_init["is_initialized"] is True
    assert data_init["neon_project_id"] is not None
    assert data_init["neon_database_name"] == "neondb"
    assert len(fake_neon.executed_ddls) > 0

    # 7. Simular que Neon ya tiene la tabla articulo
    fake_neon.introspected_tables = {
        "articulo": CurrentPostgresTable(
            name="articulo",
            columns={
                "id": CurrentPostgresColumn(name="id", data_type="UUID", is_nullable=False, is_primary_key=True),
                "nombre": CurrentPostgresColumn(name="nombre", data_type="TEXT", is_nullable=False, is_primary_key=False),
            },
            primary_keys=["id"],
            foreign_keys={},
        )
    }

    # 8. POST /sync sin cambios -> has_changes=False
    res_sync_noop = client.post(f"/api/projects/{project.id}/integrations/neon/sync")
    assert res_sync_noop.status_code == 200
    assert res_sync_noop.json()["has_changes"] is False

    # 9. Modificar diagrama: agregar nuevo atributo 'precio'
    attr_precio = DiagramAttributeModel(
        class_id=cls.id,
        name="precio",
        data_type=DiagramAttributeDataType.DECIMAL,
        position=2,
        is_nullable=True,
    )
    session.add(attr_precio)
    session.commit()

    # 10. POST /sync con cambios -> has_changes=True, added_columns contiene 'precio'
    res_sync_changes = client.post(f"/api/projects/{project.id}/integrations/neon/sync")
    assert res_sync_changes.status_code == 200
    data_sync = res_sync_changes.json()
    assert data_sync["has_changes"] is True
    assert "articulo" in data_sync["added_columns"]
    assert "precio" in data_sync["added_columns"]["articulo"]
