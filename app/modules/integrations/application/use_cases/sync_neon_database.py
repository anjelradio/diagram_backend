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
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.postgres_diagram_validator import (
    PostgresDiagramValidator,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    PostgresMigrationSummary,
    PostgresSchemaDiffService,
)
from app.modules.integrations.application.services.postgres_target_schema_builder import (
    PostgresTargetSchemaBuilder,
)
from app.modules.integrations.application.use_cases.initialize_neon_project import (
    InitializeNeonProjectCommand,
    InitializeNeonProjectUseCase,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NeonIntegrationNotConfiguredException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class SyncNeonDatabaseCommand:
    """Comando para sincronizar la base de datos de Neon como un espejo completo del diagrama."""

    project_id: UUID
    user_id: str


class SyncNeonDatabaseUseCase:
    """Sincroniza la base de datos en Neon ejecutando el motor Versus (exclusivo OWNER)."""

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

    def execute(self, command: SyncNeonDatabaseCommand) -> PostgresMigrationSummary:
        # 1. Autorización: Exclusivo OWNER
        self.access_policy.ensure_owner_access(command.project_id, command.user_id)

        # 2. Obtener integración
        integration = self.integration_repository.find_by_project_and_provider(
            project_id=command.project_id,
            provider=IntegrationProvider.NEON,
        )
        if integration is None or not integration.encrypted_api_key:
            raise NeonIntegrationNotConfiguredException()

        # Si aún no fue inicializado, inicializar automáticamente
        if not integration.is_initialized:
            init_uc = InitializeNeonProjectUseCase(
                access_policy=self.access_policy,
                integration_repository=self.integration_repository,
                project_repository=self.project_repository,
                class_repository=self.class_repository,
                attribute_repository=self.attribute_repository,
                relation_repository=self.relation_repository,
                crypto_service=self.crypto_service,
                neon_provider=self.neon_provider,
                uow=self.uow,
            )
            init_uc.execute(InitializeNeonProjectCommand(project_id=command.project_id, user_id=command.user_id))
            # Recargar integración actualizada
            integration = self.integration_repository.find_by_project_and_provider(
                project_id=command.project_id,
                provider=IntegrationProvider.NEON,
            )
            raw_summary = (integration.config_json or {}).get("last_sync_summary") or {}
            return PostgresMigrationSummary(
                created_tables=raw_summary.get("created_tables", []),
                dropped_tables=raw_summary.get("dropped_tables", []),
                added_columns=raw_summary.get("added_columns", {}),
                dropped_columns=raw_summary.get("dropped_columns", {}),
                altered_columns=raw_summary.get("altered_columns", {}),
                added_foreign_keys=raw_summary.get("added_foreign_keys", []),
                dropped_foreign_keys=raw_summary.get("dropped_foreign_keys", []),
            )

        connection_uri = self.crypto_service.decrypt(integration.encrypted_connection_uri or "")

        # 3. Snapshot actual del diagrama
        classes = self.class_repository.list_by_project_id(command.project_id)
        attributes_by_class = {c.id: self.attribute_repository.list_by_class_id(c.id) for c in classes}
        relations = self.relation_repository.list_by_project_id(command.project_id)

        # 4. Validar diagrama
        PostgresDiagramValidator.validate(classes, relations, attributes_by_class)

        # 5. Construir esquema destino deseado
        desired_schema = PostgresTargetSchemaBuilder.build(classes, relations, attributes_by_class)

        # 6. Introspección del esquema actual en Neon
        current_schema = self.neon_provider.introspect_database_schema(connection_uri)

        # 7. Motor de Versus
        plan = PostgresSchemaDiffService.generate_diff(current_schema, desired_schema)

        # 8. Ejecución DDL
        if plan.statements:
            self.neon_provider.execute_sql_migration(connection_uri, plan.statements)

        # 9. Registrar sincronización
        integration.record_neon_sync(summary=plan.summary.to_dict())
        self.integration_repository.save(integration)
        self.uow.commit()

        return plan.summary
