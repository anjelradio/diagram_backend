from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
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
from app.modules.integrations.application.services.postgres_diagram_validator import (
    PostgresDiagramValidator,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresSchema,
    PostgresSchemaDiffService,
)
from app.modules.integrations.application.services.postgres_target_schema_builder import (
    PostgresTargetSchemaBuilder,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NeonIntegrationNotConfiguredException,
    NeonProjectAlreadyInitializedException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class InitializeNeonProjectCommand:
    """Comando para aprovisionar un proyecto en Neon y desplegar el esquema inicial."""

    project_id: UUID
    user_id: str


class InitializeNeonProjectUseCase:
    """Aprovisiona y despliega por primera vez la BD en Neon (exclusivo para OWNER)."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
        project_repository: ProjectRepository,
        class_repository: DiagramClassRepository,
        attribute_repository: DiagramAttributeRepository,
        relation_repository: DiagramRelationRepository,
        crypto_service: IntegrationCryptoService,
        neon_provider: NeonIntegrationProvider,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository
        self.project_repository = project_repository
        self.class_repository = class_repository
        self.attribute_repository = attribute_repository
        self.relation_repository = relation_repository
        self.crypto_service = crypto_service
        self.neon_provider = neon_provider
        self.uow = uow

    def execute(self, command: InitializeNeonProjectCommand) -> NeonIntegrationStatusDTO:
        # 1. Autorización: Exclusivo OWNER
        self.access_policy.ensure_owner_access(command.project_id, command.user_id)

        # 2. Verificar que la integración exista con API Key
        integration = self.integration_repository.find_by_project_and_provider(
            project_id=command.project_id,
            provider=IntegrationProvider.NEON,
        )
        if integration is None or not integration.encrypted_api_key:
            raise NeonIntegrationNotConfiguredException()

        if integration.is_initialized:
            raise NeonProjectAlreadyInitializedException()

        api_key = self.crypto_service.decrypt(integration.encrypted_api_key)

        # 3. Snapshot actual del diagrama
        classes = self.class_repository.list_by_project_id(command.project_id)
        attributes_by_class = {c.id: self.attribute_repository.list_by_class_id(c.id) for c in classes}
        relations = self.relation_repository.list_by_project_id(command.project_id)

        # 4. Validar diagrama antes de tocar Neon
        PostgresDiagramValidator.validate(classes, relations, attributes_by_class)

        # 5. Construir esquema destino deseado
        desired_schema = PostgresTargetSchemaBuilder.build(classes, relations, attributes_by_class)

        # 6. Aprovisionar proyecto en Neon
        project = self.project_repository.find_by_id(command.project_id)
        project_name = project.name if project is not None else "UML Project"
        provisioned = self.neon_provider.create_project_and_database(api_key, project_name)

        # 7. Generar DDL inicial y ejecutar en Neon
        plan = PostgresSchemaDiffService.generate_diff(CurrentPostgresSchema(), desired_schema)
        if plan.statements:
            self.neon_provider.execute_sql_migration(provisioned.connection_uri, plan.statements)

        # 8. Guardar identificadores y connection string cifrada
        encrypted_conn_uri = (
            self.crypto_service.encrypt(provisioned.connection_uri)
            if provisioned.connection_uri
            else ""
        )
        integration.mark_neon_initialized(
            neon_project_id=provisioned.project_id,
            database_name=provisioned.database_name,
            branch_id=provisioned.branch_id,
            console_url=provisioned.console_url,
            encrypted_connection_uri=encrypted_conn_uri,
        )
        integration.record_neon_sync(summary=plan.summary.to_dict())

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
