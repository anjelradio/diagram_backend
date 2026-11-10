import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from sqlmodel import Session

from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionInitializedWorkspace,
    NotionIntegrationProvider,
    NotionProjectWelcomeContent,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.notion_project_snapshot_builder import (
    NotionProjectSnapshotBuilder,
)
from app.modules.integrations.application.use_cases.configure_notion_integration import (
    ConfigureNotionIntegrationCommand,
    ConfigureNotionIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.initialize_notion_project import (
    InitializeNotionProjectCommand,
    InitializeNotionProjectUseCase,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NotionIntegrationNotConfiguredException,
    NotionInvalidCredentialsException,
    NotionProjectAlreadyInitializedException,
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
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.domain.exceptions import ForbiddenException
from app.shared.infrastructure.db.better_auth import BetterAuthUser
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


class FakeNotionProvider(NotionIntegrationProvider):
    def __init__(self, is_valid: bool = True) -> None:
        self.is_valid = is_valid
        self.initialized_calls = []

    def validate_api_key(self, api_key: str, *, parent_page_id: str | None = None):
        if not self.is_valid or not api_key.startswith("ntn_"):
            return False, None, None
        return True, parent_page_id or "parent-page-uuid", "Mi Workspace"

    def initialize_project_workspace(
        self,
        *,
        api_key: str,
        parent_page_id: str,
        project_name: str,
        welcome_content: NotionProjectWelcomeContent,
    ) -> NotionInitializedWorkspace:
        self.initialized_calls.append({
            "project_name": project_name,
            "welcome_content": welcome_content,
        })
        return NotionInitializedWorkspace(
            page_id="root-page-uuid-123",
            database_id="db-uuid-456",
            page_url="https://notion.so/root-page-uuid-123",
        )

    def create_task(self, **kwargs):
        raise NotImplementedError

    def list_tasks(self, **kwargs):
        raise NotImplementedError

    def get_task(self, **kwargs):
        raise NotImplementedError

    def update_task(self, **kwargs):
        raise NotImplementedError

    def delete_task(self, **kwargs):
        raise NotImplementedError


def test_crypto_service():
    crypto = IntegrationCryptoService(secret="test-secret-key-1234567890")
    raw = "ntn_secret_token_123"
    encrypted = crypto.encrypt(raw)
    assert encrypted != raw
    assert crypto.decrypt(encrypted) == raw


def test_configure_notion_integration_owner_only_and_encryption(session: Session):
    owner_id = "user-owner"
    other_id = "user-collaborator"
    proj = ProjectModel(name="Test Project", owner_id=owner_id)
    session.add(proj)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    crypto_service = IntegrationCryptoService()
    fake_notion = FakeNotionProvider(is_valid=True)

    use_case = ConfigureNotionIntegrationUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        notion_provider=fake_notion,
        uow=uow,
    )

    # 1. Colaborador (o usuario sin permiso) no puede configurar
    with pytest.raises(ProjectNotFoundException):
        use_case.execute(
            ConfigureNotionIntegrationCommand(
                project_id=proj.id,
                user_id=other_id,
                api_key="ntn_valid_token",
            )
        )

    # 2. Token inválido falla
    fake_notion.is_valid = False
    with pytest.raises(NotionInvalidCredentialsException):
        use_case.execute(
            ConfigureNotionIntegrationCommand(
                project_id=proj.id,
                user_id=owner_id,
                api_key="invalid_token",
            )
        )

    # 3. Owner configura con éxito y se guarda encriptado
    fake_notion.is_valid = True
    status_dto = use_case.execute(
        ConfigureNotionIntegrationCommand(
            project_id=proj.id,
            user_id=owner_id,
            api_key="ntn_valid_token",
        )
    )
    assert status_dto.has_api_key is True
    assert status_dto.is_initialized is False

    saved = integration_repo.find_by_project_and_provider(proj.id, IntegrationProvider.NOTION)
    assert saved is not None
    assert saved.encrypted_api_key != "ntn_valid_token"
    assert crypto_service.decrypt(saved.encrypted_api_key) == "ntn_valid_token"


def test_initialize_notion_project_once_and_snapshot_enrichment(session: Session):
    owner_id = "user-owner"
    proj = ProjectModel(name="Tienda Kiosco", owner_id=owner_id)
    session.add(proj)
    session.commit()

    # Agregar usuario owner y miembro con nombres en BetterAuthUser
    owner_user = BetterAuthUser(id=owner_id, name="Carlos Dueño", email="carlos@test.com")
    member_user = BetterAuthUser(id="colab-1", name="Ana Desarrolladora", email="ana@test.com")
    session.add(owner_user)
    session.add(member_user)
    session.add(ProjectMemberModel(project_id=proj.id, user_id="colab-1", role="editor"))
    session.commit()

    # Agregar clases y atributos en el diagrama
    cls_prod = DiagramClassModel(project_id=proj.id, name="Producto", position_x=10, position_y=20)
    session.add(cls_prod)
    session.commit()

    attr_precio = DiagramAttributeModel(
        class_id=cls_prod.id,
        name="precio",
        data_type="DECIMAL",
        position=1,
        is_primary_key=False,
        is_foreign_key=False,
        is_nullable=False,
    )
    session.add(attr_precio)
    session.commit()

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    proj_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(proj_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    crypto_service = IntegrationCryptoService()
    fake_notion = FakeNotionProvider(is_valid=True)

    snapshot_builder = NotionProjectSnapshotBuilder(
        session=session,
        project_repository=proj_repo,
        class_repository=SQLModelDiagramClassRepository(session),
        attribute_repository=SQLModelDiagramAttributeRepository(session),
        relation_repository=SQLModelDiagramRelationRepository(session),
    )

    fake_ai = MagicMock()
    fake_ai_resp = MagicMock()
    fake_ai_resp.content = "Resumen ejecutivo del kiosco con catálogo de productos y precios."
    fake_ai.request.return_value = fake_ai_resp

    init_use_case = InitializeNotionProjectUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        snapshot_builder=snapshot_builder,
        notion_provider=fake_notion,
        ai_provider=fake_ai,
        uow=uow,
    )

    # 1. Si no hay API Key configurada falla
    with pytest.raises(NotionIntegrationNotConfiguredException):
        init_use_case.execute(
            InitializeNotionProjectCommand(
                project_id=proj.id,
                user_id=owner_id,
                description="Sistema básico",
            )
        )

    # 2. Configurar API Key
    configure_use_case = ConfigureNotionIntegrationUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        notion_provider=fake_notion,
        uow=uow,
    )
    configure_use_case.execute(
        ConfigureNotionIntegrationCommand(
            project_id=proj.id,
            user_id=owner_id,
            api_key="ntn_secret_token",
        )
    )

    # 3. Inicializar por primera vez con éxito
    status_dto = init_use_case.execute(
        InitializeNotionProjectCommand(
            project_id=proj.id,
            user_id=owner_id,
            description="Sistema para kiosco con gestión de productos.",
        )
    )
    assert status_dto.is_initialized is True
    assert status_dto.notion_page_id == "root-page-uuid-123"
    assert status_dto.notion_tasks_database_id == "db-uuid-456"

    # Verificar que el proveedor MCP recibió los colaboradores y el catálogo de clases
    assert len(fake_notion.initialized_calls) == 1
    call = fake_notion.initialized_calls[0]
    welcome: NotionProjectWelcomeContent = call["welcome_content"]
    assert "Carlos Dueño" in welcome.team_members
    assert "Ana Desarrolladora" in welcome.team_members
    assert any(c["name"] == "Producto" for c in welcome.diagram_classes_summary)

    # 4. Intento de inicializar por segunda vez DEBE ser rechazado
    with pytest.raises(NotionProjectAlreadyInitializedException):
        init_use_case.execute(
            InitializeNotionProjectCommand(
                project_id=proj.id,
                user_id=owner_id,
                description="Segundo intento ilegal",
            )
        )
