from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.integrations.application.ports.providers.neon_integration_provider import (
    NeonIntegrationProvider,
    NeonProvisionedProject,
)
from app.modules.integrations.application.queries.get_neon_integration_status import (
    GetNeonIntegrationStatusQueryHandler,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.postgres_diagram_validator import (
    PostgresDiagramValidator,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresColumn,
    CurrentPostgresSchema,
    CurrentPostgresTable,
    PostgresSchemaDiffService,
)
from app.modules.integrations.application.services.postgres_target_schema_builder import (
    PostgresTargetSchemaBuilder,
)
from app.modules.integrations.application.use_cases.configure_neon_integration import (
    ConfigureNeonIntegrationCommand,
    ConfigureNeonIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.initialize_neon_project import (
    InitializeNeonProjectCommand,
    InitializeNeonProjectUseCase,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseCommand,
    SyncNeonDatabaseUseCase,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NeonDiagramValidationException,
    NeonIntegrationNotConfiguredException,
    NeonInvalidCredentialsException,
    NeonProjectAlreadyInitializedException,
    NeonProjectNotInitializedException,
)
from app.modules.integrations.infrastructure.persistence.models.project_integration_model import (
    ProjectIntegrationModel,
)
from app.modules.integrations.infrastructure.persistence.repositories.sqlmodel_project_integration_repository import (
    SQLModelProjectIntegrationRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.domain.exceptions import ForbiddenException
from app.shared.infrastructure.db.better_auth import BetterAuthUser
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


class FakeNeonProvider(NeonIntegrationProvider):
    def __init__(self, is_valid: bool = True) -> None:
        self.is_valid = is_valid
        self.provision_calls = []
        self.executed_ddls = []
        self.introspected_tables: dict[str, CurrentPostgresTable] = {}

    def validate_api_key(self, api_key: str) -> tuple[bool, str | None]:
        if not self.is_valid or "invalid" in api_key:
            return False, "Invalid key"
        return True, "User"

    def create_project_and_database(self, api_key: str, project_name: str) -> NeonProvisionedProject:
        valid, _ = self.validate_api_key(api_key)
        if not valid:
            raise NeonInvalidCredentialsException()
        prov = NeonProvisionedProject(
            project_id=f"neon-proj-{uuid4().hex[:8]}",
            database_name="neondb",
            branch_id="br-main-1",
            console_url="https://console.neon.tech/app/projects/test",
            connection_uri="postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require",
        )
        self.provision_calls.append(prov)
        return prov

    def introspect_database_schema(self, connection_uri: str) -> CurrentPostgresSchema:
        return CurrentPostgresSchema(tables=dict(self.introspected_tables))

    def execute_sql_migration(self, connection_uri: str, statements: list[str]) -> bool:
        self.executed_ddls.extend(statements)
        return True


def setup_neon_test_context(session: Session, is_neon_valid: bool = True):
    owner_id = f"owner-{uuid4().hex[:6]}"
    editor_id = f"editor-{uuid4().hex[:6]}"
    reader_id = f"reader-{uuid4().hex[:6]}"

    session.add(BetterAuthUser(id=owner_id, name="Owner User", email="owner@test.com", emailVerified=True, createdAt=datetime.now(timezone.utc), updatedAt=datetime.now(timezone.utc)))
    session.add(BetterAuthUser(id=editor_id, name="Editor User", email="editor@test.com", emailVerified=True, createdAt=datetime.now(timezone.utc), updatedAt=datetime.now(timezone.utc)))
    session.add(BetterAuthUser(id=reader_id, name="Reader User", email="reader@test.com", emailVerified=True, createdAt=datetime.now(timezone.utc), updatedAt=datetime.now(timezone.utc)))

    project = ProjectModel(name="E-Commerce API", owner_id=owner_id)
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(ProjectMemberModel(project_id=project.id, user_id=editor_id, role="EDITOR", status="ACTIVE"))
    session.add(ProjectMemberModel(project_id=project.id, user_id=reader_id, role="READER", status="ACTIVE"))
    session.commit()

    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    rel_repo = SQLModelDiagramRelationRepository(session)
    uow = SqlModelUnitOfWork(session, InMemoryEventBus())

    crypto_service = IntegrationCryptoService(secret="0123456789abcdef0123456789abcdef")
    neon_provider = FakeNeonProvider(is_valid=is_neon_valid)
    validator = PostgresDiagramValidator()
    target_builder = PostgresTargetSchemaBuilder()
    diff_service = PostgresSchemaDiffService()

    status_query = GetNeonIntegrationStatusQueryHandler(
        integration_repository=integration_repo,
        access_policy=access_policy,
    )

    configure_uc = ConfigureNeonIntegrationUseCase(
        integration_repository=integration_repo,
        access_policy=access_policy,
        crypto_service=crypto_service,
        neon_provider=neon_provider,
        uow=uow,
    )

    initialize_uc = InitializeNeonProjectUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        project_repository=project_repo,
        class_repository=class_repo,
        attribute_repository=attr_repo,
        relation_repository=rel_repo,
        crypto_service=crypto_service,
        neon_provider=neon_provider,
        uow=uow,
    )

    sync_uc = SyncNeonDatabaseUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        project_repository=project_repo,
        class_repository=class_repo,
        attribute_repository=attr_repo,
        relation_repository=rel_repo,
        crypto_service=crypto_service,
        neon_provider=neon_provider,
        uow=uow,
    )

    return {
        "project": project,
        "owner_id": owner_id,
        "editor_id": editor_id,
        "reader_id": reader_id,
        "session": session,
        "status_query": status_query,
        "configure_uc": configure_uc,
        "initialize_uc": initialize_uc,
        "sync_uc": sync_uc,
        "neon_provider": neon_provider,
        "integration_repo": integration_repo,
        "crypto_service": crypto_service,
    }


def test_get_status_unconfigured(session: Session):
    ctx = setup_neon_test_context(session)
    status = ctx["status_query"].execute(ctx["project"].id, ctx["owner_id"])
    assert status.has_api_key is False
    assert status.is_initialized is False
    assert status.neon_project_id is None


def test_configure_neon_owner_success(session: Session):
    ctx = setup_neon_test_context(session)
    cmd = ConfigureNeonIntegrationCommand(
        project_id=ctx["project"].id,
        user_id=ctx["owner_id"],
        api_key="napi_valid_token_123",
    )
    status = ctx["configure_uc"].execute(cmd)
    assert status.has_api_key is True
    assert status.is_initialized is False

    # Check persistence
    integration = ctx["integration_repo"].find_by_project_and_provider(
        ctx["project"].id, IntegrationProvider.NEON
    )
    assert integration is not None
    decrypted = ctx["crypto_service"].decrypt(integration.encrypted_api_key)
    assert decrypted == "napi_valid_token_123"


def test_configure_neon_non_owner_forbidden(session: Session):
    ctx = setup_neon_test_context(session)
    cmd = ConfigureNeonIntegrationCommand(
        project_id=ctx["project"].id,
        user_id=ctx["editor_id"],
        api_key="napi_valid_token_123",
    )
    with pytest.raises(ForbiddenException):
        ctx["configure_uc"].execute(cmd)


def test_configure_neon_invalid_api_key(session: Session):
    ctx = setup_neon_test_context(session, is_neon_valid=False)
    cmd = ConfigureNeonIntegrationCommand(
        project_id=ctx["project"].id,
        user_id=ctx["owner_id"],
        api_key="napi_invalid_token",
    )
    with pytest.raises(NeonInvalidCredentialsException):
        ctx["configure_uc"].execute(cmd)


def test_initialize_neon_empty_diagram_fails(session: Session):
    ctx = setup_neon_test_context(session)
    # Configure first
    ctx["configure_uc"].execute(
        ConfigureNeonIntegrationCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
            api_key="napi_valid_token_123",
        )
    )

    # Initialize with empty diagram
    with pytest.raises(NeonDiagramValidationException) as exc_info:
        ctx["initialize_uc"].execute(
            InitializeNeonProjectCommand(
                project_id=ctx["project"].id,
                user_id=ctx["owner_id"],
            )
        )
    assert "vacío" in str(exc_info.value)


def test_initialize_neon_duplicate_names_validation(session: Session):
    ctx = setup_neon_test_context(session)
    ctx["configure_uc"].execute(
        ConfigureNeonIntegrationCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
            api_key="napi_valid_token_123",
        )
    )

    # Add duplicate classes
    cls1 = DiagramClassModel(project_id=ctx["project"].id, name="Usuario", position_x=0, position_y=0)
    cls2 = DiagramClassModel(project_id=ctx["project"].id, name="usuario", position_x=10, position_y=10)
    session.add(cls1)
    session.add(cls2)
    session.commit()

    with pytest.raises(NeonDiagramValidationException) as exc_info:
        ctx["initialize_uc"].execute(
            InitializeNeonProjectCommand(
                project_id=ctx["project"].id,
                user_id=ctx["owner_id"],
            )
        )
    assert "clases duplicadas" in str(exc_info.value)


def test_initialize_and_sync_neon_success_flow(session: Session):
    ctx = setup_neon_test_context(session)
    # 1. Configurar
    ctx["configure_uc"].execute(
        ConfigureNeonIntegrationCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
            api_key="napi_valid_token_123",
        )
    )

    # 2. Agregar clases válidas
    cls_user = DiagramClassModel(project_id=ctx["project"].id, name="Usuario", position_x=0, position_y=0)
    session.add(cls_user)
    session.commit()
    session.refresh(cls_user)

    attr_id = DiagramAttributeModel(
        class_id=cls_user.id,
        name="id",
        data_type=DiagramAttributeDataType.UUID,
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    attr_email = DiagramAttributeModel(
        class_id=cls_user.id,
        name="email",
        data_type=DiagramAttributeDataType.TEXT,
        position=1,
        is_nullable=False,
    )
    session.add(attr_id)
    session.add(attr_email)
    session.commit()

    # 3. Inicializar
    init_res = ctx["initialize_uc"].execute(
        InitializeNeonProjectCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
        )
    )
    assert init_res.is_initialized is True
    assert init_res.neon_project_id is not None
    assert init_res.neon_database_name == "neondb"
    assert len(ctx["neon_provider"].executed_ddls) > 0

    # 4. Sincronizar sin cambios en el diagrama (simulando que Neon ya tiene usuario)
    ctx["neon_provider"].introspected_tables = {
        "usuario": CurrentPostgresTable(
            name="usuario",
            columns={
                "id": CurrentPostgresColumn(name="id", data_type="UUID", is_nullable=False, is_primary_key=True),
                "email": CurrentPostgresColumn(name="email", data_type="TEXT", is_nullable=False, is_primary_key=False),
            },
            primary_keys=["id"],
            foreign_keys={},
        )
    }
    sync_summary = ctx["sync_uc"].execute(
        SyncNeonDatabaseCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
        )
    )
    assert sync_summary.has_changes is False

    # 5. Modificar diagrama: agregar nuevo atributo a Usuario
    attr_bio = DiagramAttributeModel(
        class_id=cls_user.id,
        name="bio",
        data_type=DiagramAttributeDataType.TEXT,
        position=2,
        is_nullable=False,  # En diagrama puede ser NOT NULL, pero motor de diff forzará NULL seguro
    )
    session.add(attr_bio)
    session.commit()

    sync_summary_2 = ctx["sync_uc"].execute(
        SyncNeonDatabaseCommand(
            project_id=ctx["project"].id,
            user_id=ctx["owner_id"],
        )
    )
    assert sync_summary_2.has_changes is True
    assert "usuario" in sync_summary_2.added_columns
    assert "bio" in sync_summary_2.added_columns["usuario"]


def test_neon_mcp_provider_validate_api_key_success():
    from app.modules.integrations.infrastructure.external.neon_mcp_provider import (
        NeonMcpProvider,
    )

    provider = NeonMcpProvider()
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"projects": [{"name": "my-app"}]}
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        valid, label = provider.validate_api_key("napi_test_123")
        assert valid is True
        assert label == "Neon (my-app)"
        mock_client.get.assert_called_with(
            "https://console.neon.tech/api/v2/projects?limit=1",
            headers={
                "Authorization": "Bearer napi_test_123",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )


def test_neon_mcp_provider_validate_api_key_unauthorized():
    from app.modules.integrations.infrastructure.external.neon_mcp_provider import (
        NeonMcpProvider,
    )

    provider = NeonMcpProvider()
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        valid, label = provider.validate_api_key("napi_invalid")
        assert valid is False
        assert "no autorizada o expirada" in (label or "")
