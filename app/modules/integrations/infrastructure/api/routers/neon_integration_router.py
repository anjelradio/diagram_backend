from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser
from app.modules.integrations.application.queries.get_neon_integration_status import (
    GetNeonIntegrationStatusQueryHandler,
)
from app.modules.integrations.application.use_cases.configure_neon_integration import (
    ConfigureNeonIntegrationCommand,
    ConfigureNeonIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.initialize_neon_project import (
    InitializeNeonProjectCommand,
    InitializeNeonProjectUseCase,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseCommand,
    SyncNeonDatabaseUseCase,
)
from app.modules.integrations.infrastructure.api.dependencies import (
    get_configure_neon_use_case,
    get_initialize_neon_use_case,
    get_neon_status_query,
    get_sync_neon_use_case,
)
from app.modules.integrations.infrastructure.api.schemas.neon_integration_schemas import (
    ConfigureNeonIntegrationRequest,
    NeonIntegrationStatusRead,
    NeonSyncResultRead,
)

router = APIRouter(prefix="/projects/{project_id}/integrations/neon", tags=["Integrations - Neon"])


@router.get("", response_model=NeonIntegrationStatusRead)
def get_neon_integration_status(
    project_id: UUID,
    current_user: CurrentUser,
    query_handler: GetNeonIntegrationStatusQueryHandler = Depends(get_neon_status_query),
) -> NeonIntegrationStatusRead:
    """Consulta el estado actual de la integración de Neon del proyecto."""
    dto = query_handler.execute(project_id, current_user.user_id)
    return NeonIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        neon_project_id=dto.neon_project_id,
        neon_database_name=dto.neon_database_name,
        neon_console_url=dto.neon_console_url,
        neon_branch_id=dto.neon_branch_id,
        last_synced_at=dto.last_synced_at,
    )


@router.put("/config", response_model=NeonIntegrationStatusRead)
def configure_neon_integration(
    project_id: UUID,
    payload: ConfigureNeonIntegrationRequest,
    current_user: CurrentUser,
    use_case: ConfigureNeonIntegrationUseCase = Depends(get_configure_neon_use_case),
) -> NeonIntegrationStatusRead:
    """Registra o actualiza la API Key de Neon de forma cifrada (exclusivo OWNER)."""
    command = ConfigureNeonIntegrationCommand(
        project_id=project_id,
        user_id=current_user.user_id,
        api_key=payload.api_key,
    )
    dto = use_case.execute(command)
    return NeonIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        neon_project_id=dto.neon_project_id,
        neon_database_name=dto.neon_database_name,
        neon_console_url=dto.neon_console_url,
        neon_branch_id=dto.neon_branch_id,
        last_synced_at=dto.last_synced_at,
    )


@router.post("/initialize", response_model=NeonIntegrationStatusRead, status_code=status.HTTP_201_CREATED)
def initialize_neon_project(
    project_id: UUID,
    current_user: CurrentUser,
    use_case: InitializeNeonProjectUseCase = Depends(get_initialize_neon_use_case),
) -> NeonIntegrationStatusRead:
    """Inicializa por primera vez el proyecto y la base de datos en Neon desplegando el diagrama (exclusivo OWNER)."""
    command = InitializeNeonProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    dto = use_case.execute(command)
    return NeonIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        neon_project_id=dto.neon_project_id,
        neon_database_name=dto.neon_database_name,
        neon_console_url=dto.neon_console_url,
        neon_branch_id=dto.neon_branch_id,
        last_synced_at=dto.last_synced_at,
    )


@router.post("/sync", response_model=NeonSyncResultRead)
def sync_neon_database(
    project_id: UUID,
    current_user: CurrentUser,
    use_case: SyncNeonDatabaseUseCase = Depends(get_sync_neon_use_case),
) -> NeonSyncResultRead:
    """Sincroniza la base de datos de Neon como espejo del diagrama actual vía Versus (exclusivo OWNER)."""
    command = SyncNeonDatabaseCommand(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    summary = use_case.execute(command)
    return NeonSyncResultRead(
        has_changes=summary.has_changes,
        created_tables=summary.created_tables,
        dropped_tables=summary.dropped_tables,
        added_columns=summary.added_columns,
        dropped_columns=summary.dropped_columns,
        altered_columns=summary.altered_columns,
        added_foreign_keys=summary.added_foreign_keys,
        dropped_foreign_keys=summary.dropped_foreign_keys,
    )
