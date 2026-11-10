from app.modules.integrations.domain.entities.project_integration import (
    ProjectIntegration,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.infrastructure.persistence.models.project_integration_model import (
    ProjectIntegrationModel,
)


class ProjectIntegrationMapper:
    """Mapeador estático entre entidad ProjectIntegration y modelo ProjectIntegrationModel."""

    @staticmethod
    def to_domain(model: ProjectIntegrationModel) -> ProjectIntegration:
        return ProjectIntegration.reconstitute(
            id=model.id,
            project_id=model.project_id,
            provider=IntegrationProvider(model.provider),
            encrypted_api_key=model.encrypted_api_key,
            external_page_id=model.external_page_id,
            external_database_id=model.external_database_id,
            config_json=model.config_json,
            created_date=model.created_date,
            modified_date=model.modified_date,
            is_active=(model.deleted_date is None),
        )

    @staticmethod
    def to_model(entity: ProjectIntegration) -> ProjectIntegrationModel:
        return ProjectIntegrationModel(
            id=entity.id,
            project_id=entity.project_id,
            provider=entity.provider.value,
            encrypted_api_key=entity.encrypted_api_key,
            external_page_id=entity.external_page_id,
            external_database_id=entity.external_database_id,
            config_json=entity.config_json,
            created_date=entity.created_date,
            modified_date=entity.modified_date,
            deleted_date=None if entity.is_active else entity.modified_date,
        )
