from fastapi import Depends
from sqlmodel import Session

from app.core.dependencies import get_event_bus, get_session
from app.modules.assistant.infrastructure.external.qwen_ai_provider import QwenAiProvider
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
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
from app.modules.integrations.application.queries.get_neon_integration_status import (
    GetNeonIntegrationStatusQueryHandler,
)
from app.modules.integrations.application.queries.get_notion_integration_status import (
    GetNotionIntegrationStatusQueryHandler,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.notion_project_snapshot_builder import (
    NotionProjectSnapshotBuilder,
)
from app.modules.integrations.application.use_cases.configure_neon_integration import (
    ConfigureNeonIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.configure_notion_integration import (
    ConfigureNotionIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.initialize_neon_project import (
    InitializeNeonProjectUseCase,
)
from app.modules.integrations.application.use_cases.initialize_notion_project import (
    InitializeNotionProjectUseCase,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseUseCase,
)
from app.modules.integrations.infrastructure.external.neon_mcp_provider import (
    NeonMcpProvider,
)
from app.modules.integrations.infrastructure.external.notion_mcp_provider import (
    NotionMcpProvider,
)
from app.modules.integrations.infrastructure.persistence.repositories.sqlmodel_project_integration_repository import (
    SQLModelProjectIntegrationRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def get_crypto_service() -> IntegrationCryptoService:
    return IntegrationCryptoService()


def get_notion_provider() -> NotionMcpProvider:
    return NotionMcpProvider()


def get_notion_status_query(
    session: Session = Depends(get_session),
) -> GetNotionIntegrationStatusQueryHandler:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    return GetNotionIntegrationStatusQueryHandler(access_policy, integration_repo)


def get_configure_notion_use_case(
    session: Session = Depends(get_session),
    crypto_service: IntegrationCryptoService = Depends(get_crypto_service),
    notion_provider: NotionMcpProvider = Depends(get_notion_provider),
) -> ConfigureNotionIntegrationUseCase:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    uow = SqlModelUnitOfWork(session, get_event_bus())
    return ConfigureNotionIntegrationUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        notion_provider=notion_provider,
        uow=uow,
    )


def get_initialize_notion_use_case(
    session: Session = Depends(get_session),
    crypto_service: IntegrationCryptoService = Depends(get_crypto_service),
    notion_provider: NotionMcpProvider = Depends(get_notion_provider),
) -> InitializeNotionProjectUseCase:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    rel_repo = SQLModelDiagramRelationRepository(session)
    snapshot_builder = NotionProjectSnapshotBuilder(
        session=session,
        project_repository=project_repo,
        class_repository=class_repo,
        attribute_repository=attr_repo,
        relation_repository=rel_repo,
    )
    ai_provider = QwenAiProvider()
    uow = SqlModelUnitOfWork(session, get_event_bus())
    return InitializeNotionProjectUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        snapshot_builder=snapshot_builder,
        notion_provider=notion_provider,
        ai_provider=ai_provider,
        uow=uow,
    )


def get_neon_provider() -> NeonMcpProvider:
    return NeonMcpProvider()


def get_neon_status_query(
    session: Session = Depends(get_session),
) -> GetNeonIntegrationStatusQueryHandler:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    return GetNeonIntegrationStatusQueryHandler(access_policy, integration_repo)


def get_configure_neon_use_case(
    session: Session = Depends(get_session),
    crypto_service: IntegrationCryptoService = Depends(get_crypto_service),
    neon_provider: NeonMcpProvider = Depends(get_neon_provider),
) -> ConfigureNeonIntegrationUseCase:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    uow = SqlModelUnitOfWork(session, get_event_bus())
    return ConfigureNeonIntegrationUseCase(
        access_policy=access_policy,
        integration_repository=integration_repo,
        crypto_service=crypto_service,
        neon_provider=neon_provider,
        uow=uow,
    )


def get_initialize_neon_use_case(
    session: Session = Depends(get_session),
    crypto_service: IntegrationCryptoService = Depends(get_crypto_service),
    neon_provider: NeonMcpProvider = Depends(get_neon_provider),
) -> InitializeNeonProjectUseCase:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    rel_repo = SQLModelDiagramRelationRepository(session)
    uow = SqlModelUnitOfWork(session, get_event_bus())
    return InitializeNeonProjectUseCase(
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


def get_sync_neon_use_case(
    session: Session = Depends(get_session),
    crypto_service: IntegrationCryptoService = Depends(get_crypto_service),
    neon_provider: NeonMcpProvider = Depends(get_neon_provider),
) -> SyncNeonDatabaseUseCase:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    integration_repo = SQLModelProjectIntegrationRepository(session)
    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    rel_repo = SQLModelDiagramRelationRepository(session)
    uow = SqlModelUnitOfWork(session, get_event_bus())
    return SyncNeonDatabaseUseCase(
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
