from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.integrations.application.ports.providers.neon_integration_provider import (
    NeonIntegrationProvider,
)
from app.modules.integrations.application.queries.get_neon_integration_status import (
    NeonIntegrationStatusDTO,
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
    NeonInvalidCredentialsException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class ConfigureNeonIntegrationCommand:
    """Comando para registrar o actualizar la API Key de Neon."""

    project_id: UUID
    user_id: str
    api_key: str


class ConfigureNeonIntegrationUseCase:
    """Configura de forma encriptada la API Key de Neon (exclusivo para OWNER)."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
        crypto_service: IntegrationCryptoService,
        neon_provider: NeonIntegrationProvider,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository
        self.crypto_service = crypto_service
        self.neon_provider = neon_provider
        self.uow = uow

    def execute(self, command: ConfigureNeonIntegrationCommand) -> NeonIntegrationStatusDTO:
        # 1. Autorización: Exclusivo OWNER
        self.access_policy.ensure_owner_access(command.project_id, command.user_id)

        clean_api_key = (command.api_key or "").strip()
        if not clean_api_key:
            raise NeonInvalidCredentialsException("La API Key de Neon no puede estar vacía.")

        # 2. Validación activa contra la API de Neon
        is_valid, err_msg = self.neon_provider.validate_api_key(clean_api_key)
        if not is_valid:
            raise NeonInvalidCredentialsException(err_msg or "La API Key de Neon no es válida.")

        # 3. Encriptar API Key
        encrypted_api_key = self.crypto_service.encrypt(clean_api_key)

        # 4. Buscar o crear integración
        integration = self.integration_repository.find_by_project_and_provider(
            project_id=command.project_id,
            provider=IntegrationProvider.NEON,
        )
        if integration is None:
            integration = ProjectIntegration.create(
                project_id=command.project_id,
                provider=IntegrationProvider.NEON,
                encrypted_api_key=encrypted_api_key,
            )
        else:
            integration.update_credentials(
                encrypted_api_key=encrypted_api_key,
            )

        self.integration_repository.save(integration)
        self.uow.commit()

        return NeonIntegrationStatusDTO(
            project_id=integration.project_id,
            provider=integration.provider.value,
            has_api_key=bool(integration.encrypted_api_key),
            is_initialized=integration.is_initialized,
            neon_project_id=integration.neon_project_id,
            neon_database_name=integration.neon_database_name,
            neon_console_url=integration.neon_console_url,
            neon_branch_id=integration.neon_branch_id,
            last_synced_at=integration.last_synced_at,
        )
