from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)


@dataclass(frozen=True, slots=True)
class NotionIntegrationStatusDTO:
    """DTO de lectura inmutable para el estado de la integración de Notion."""

    project_id: UUID
    provider: str
    has_api_key: bool
    is_initialized: bool
    notion_page_id: str | None
    notion_tasks_database_id: str | None
    notion_page_url: str | None


class GetNotionIntegrationStatusQueryHandler:
    """Maneja la consulta del estado de integración de Notion para un proyecto."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository

    def execute(self, project_id: UUID, user_id: str) -> NotionIntegrationStatusDTO:
        self.access_policy.ensure_read_access(project_id, user_id)
        integration = self.integration_repository.find_by_project_and_provider(
            project_id=project_id,
            provider=IntegrationProvider.NOTION,
        )
        if integration is None:
            return NotionIntegrationStatusDTO(
                project_id=project_id,
                provider=IntegrationProvider.NOTION.value,
                has_api_key=False,
                is_initialized=False,
                notion_page_id=None,
                notion_tasks_database_id=None,
                notion_page_url=None,
            )

        return NotionIntegrationStatusDTO(
            project_id=project_id,
            provider=integration.provider.value,
            has_api_key=bool(integration.encrypted_api_key),
            is_initialized=integration.is_initialized,
            notion_page_id=integration.external_page_id,
            notion_tasks_database_id=integration.external_database_id,
            notion_page_url=integration.notion_page_url,
        )
