from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionIntegrationProvider,
)
from app.modules.integrations.application.queries.get_notion_integration_status import (
    NotionIntegrationStatusDTO,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.domain.entities.project_integration import (
    ProjectIntegration,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NotionInvalidCredentialsException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class ConfigureNotionIntegrationCommand:
    """Comando para registrar o actualizar la API Key de Notion."""

    project_id: UUID
    user_id: str
    api_key: str
    parent_page_id: str | None = None


class ConfigureNotionIntegrationUseCase:
    """Configura de forma encriptada la API Key de Notion (exclusivo para OWNER)."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
        crypto_service: IntegrationCryptoService,
        notion_provider: NotionIntegrationProvider,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository
        self.crypto_service = crypto_service
        self.notion_provider = notion_provider
        self.uow = uow

    def execute(self, command: ConfigureNotionIntegrationCommand) -> NotionIntegrationStatusDTO:
        # 1. Autorización: Exclusivo OWNER
        self.access_policy.ensure_owner_access(command.project_id, command.user_id)

        # 2. Validar credenciales frente a Notion
        is_valid, resolved_parent_id, workspace_name = self.notion_provider.validate_api_key(
            command.api_key,
            parent_page_id=command.parent_page_id,
        )
        if not is_valid:
            raise NotionInvalidCredentialsException()

        # 3. Cifrar token
        encrypted_key = self.crypto_service.encrypt(command.api_key)

        # 4. Persistir o actualizar integración
        integration = self.integration_repository.find_by_project_and_provider(
            command.project_id,
            IntegrationProvider.NOTION,
        )
        if integration is None:
            integration = ProjectIntegration.create(
                project_id=command.project_id,
                provider=IntegrationProvider.NOTION,
                encrypted_api_key=encrypted_key,
                parent_page_id=resolved_parent_id,
                workspace_name=workspace_name,
            )
        else:
            integration.update_credentials(
                encrypted_api_key=encrypted_key,
                parent_page_id=resolved_parent_id,
                workspace_name=workspace_name,
            )

        self.integration_repository.save(integration)
        self.uow.commit()

        return NotionIntegrationStatusDTO(
            project_id=integration.project_id,
            provider=integration.provider.value,
            has_api_key=True,
            is_initialized=integration.is_initialized,
            notion_page_id=integration.external_page_id,
            notion_tasks_database_id=integration.external_database_id,
            notion_page_url=integration.notion_page_url,
        )
