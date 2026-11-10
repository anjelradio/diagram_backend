from __future__ import annotations

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
class NeonIntegrationStatusDTO:
    """DTO inmutable para el estado de integración de Neon."""

    project_id: UUID
    provider: str
    has_api_key: bool
    is_initialized: bool
    neon_project_id: str | None
    neon_database_name: str | None
    neon_console_url: str | None
    neon_branch_id: str | None
    last_synced_at: str | None


class GetNeonIntegrationStatusQueryHandler:
    """Maneja la consulta del estado de la integración de Neon para un proyecto."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository

    def execute(self, project_id: UUID, user_id: str) -> NeonIntegrationStatusDTO:
        self.access_policy.ensure_read_access(project_id, user_id)
        integration = self.integration_repository.find_by_project_and_provider(
            project_id=project_id,
            provider=IntegrationProvider.NEON,
        )
        if integration is None:
            return NeonIntegrationStatusDTO(
                project_id=project_id,
                provider=IntegrationProvider.NEON.value,
                has_api_key=False,
                is_initialized=False,
                neon_project_id=None,
                neon_database_name=None,
                neon_console_url=None,
                neon_branch_id=None,
                last_synced_at=None,
            )

        return NeonIntegrationStatusDTO(
            project_id=project_id,
            provider=integration.provider.value,
            has_api_key=bool(integration.encrypted_api_key),
            is_initialized=integration.is_initialized,
            neon_project_id=integration.neon_project_id,
            neon_database_name=integration.neon_database_name,
            neon_console_url=integration.neon_console_url,
            neon_branch_id=integration.neon_branch_id,
            last_synced_at=integration.last_synced_at,
        )
