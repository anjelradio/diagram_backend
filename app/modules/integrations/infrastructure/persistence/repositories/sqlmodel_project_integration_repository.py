from uuid import UUID
from sqlmodel import Session, select

from app.modules.integrations.domain.entities.project_integration import (
    ProjectIntegration,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.modules.integrations.infrastructure.persistence.mappers.project_integration_mapper import (
    ProjectIntegrationMapper,
)
from app.modules.integrations.infrastructure.persistence.models.project_integration_model import (
    ProjectIntegrationModel,
)
from app.shared.infrastructure.db.base_model import utc_now


class SQLModelProjectIntegrationRepository(ProjectIntegrationRepository):
    """Implementación SQLModel del repositorio de integraciones."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, integration: ProjectIntegration) -> ProjectIntegration:
        model = self.session.get(ProjectIntegrationModel, integration.id)
        if model is None:
            model = ProjectIntegrationMapper.to_model(integration)
            self.session.add(model)
        else:
            model.encrypted_api_key = integration.encrypted_api_key
            model.external_page_id = integration.external_page_id
            model.external_database_id = integration.external_database_id
            model.config_json = dict(integration.config_json)
            model.modified_date = utc_now()
            model.deleted_date = None if integration.is_active else utc_now()
            self.session.add(model)
        return integration

    def find_by_id(self, integration_id: UUID) -> ProjectIntegration | None:
        statement = select(ProjectIntegrationModel).where(
            ProjectIntegrationModel.id == integration_id,
            ProjectIntegrationModel.deleted_date.is_(None),
        )
        record = self.session.exec(statement).first()
        if record is None:
            return None
        return ProjectIntegrationMapper.to_domain(record)

    def find_by_project_and_provider(
        self,
        project_id: UUID,
        provider: IntegrationProvider,
    ) -> ProjectIntegration | None:
        statement = select(ProjectIntegrationModel).where(
            ProjectIntegrationModel.project_id == project_id,
            ProjectIntegrationModel.provider == provider.value,
            ProjectIntegrationModel.deleted_date.is_(None),
        )
        record = self.session.exec(statement).first()
        if record is None:
            return None
        return ProjectIntegrationMapper.to_domain(record)
