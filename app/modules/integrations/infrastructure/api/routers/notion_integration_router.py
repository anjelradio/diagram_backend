from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser
from app.modules.integrations.application.queries.get_notion_integration_status import (
    GetNotionIntegrationStatusQueryHandler,
)
from app.modules.integrations.application.use_cases.configure_notion_integration import (
    ConfigureNotionIntegrationCommand,
    ConfigureNotionIntegrationUseCase,
)
from app.modules.integrations.application.use_cases.initialize_notion_project import (
    InitializeNotionProjectCommand,
    InitializeNotionProjectUseCase,
)
from app.modules.integrations.infrastructure.api.dependencies import (
    get_configure_notion_use_case,
    get_initialize_notion_use_case,
    get_notion_status_query,
)
from app.modules.integrations.infrastructure.api.schemas.notion_integration_schemas import (
    ConfigureNotionIntegrationRequest,
    InitializeNotionProjectRequest,
    NotionIntegrationStatusRead,
)

router = APIRouter(prefix="/projects/{project_id}/integrations/notion", tags=["Integrations - Notion"])


@router.get("", response_model=NotionIntegrationStatusRead)
def get_notion_integration_status(
    project_id: UUID,
    current_user: CurrentUser,
    query_handler: GetNotionIntegrationStatusQueryHandler = Depends(get_notion_status_query),
) -> NotionIntegrationStatusRead:
    """Consulta el estado actual de la integración de Notion del proyecto."""
    dto = query_handler.execute(project_id, current_user.user_id)
    return NotionIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        notion_page_id=dto.notion_page_id,
        notion_tasks_database_id=dto.notion_tasks_database_id,
        notion_page_url=dto.notion_page_url,
    )


@router.put("/config", response_model=NotionIntegrationStatusRead)
def configure_notion_integration(
    project_id: UUID,
    payload: ConfigureNotionIntegrationRequest,
    current_user: CurrentUser,
    use_case: ConfigureNotionIntegrationUseCase = Depends(get_configure_notion_use_case),
) -> NotionIntegrationStatusRead:
    """Registra o actualiza la API Key de Notion de forma cifrada (exclusivo OWNER)."""
    command = ConfigureNotionIntegrationCommand(
        project_id=project_id,
        user_id=current_user.user_id,
        api_key=payload.api_key,
        parent_page_id=payload.parent_page_id,
    )
    dto = use_case.execute(command)
    return NotionIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        notion_page_id=dto.notion_page_id,
        notion_tasks_database_id=dto.notion_tasks_database_id,
        notion_page_url=dto.notion_page_url,
    )


@router.post("/initialize", response_model=NotionIntegrationStatusRead, status_code=status.HTTP_201_CREATED)
def initialize_notion_project(
    project_id: UUID,
    payload: InitializeNotionProjectRequest,
    current_user: CurrentUser,
    use_case: InitializeNotionProjectUseCase = Depends(get_initialize_notion_use_case),
) -> NotionIntegrationStatusRead:
    """Inicializa por única vez la página raíz y base de datos de tareas en Notion (exclusivo OWNER)."""
    command = InitializeNotionProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
        description=payload.description,
    )
    dto = use_case.execute(command)
    return NotionIntegrationStatusRead(
        project_id=dto.project_id,
        provider=dto.provider,
        has_api_key=dto.has_api_key,
        is_initialized=dto.is_initialized,
        notion_page_id=dto.notion_page_id,
        notion_tasks_database_id=dto.notion_tasks_database_id,
        notion_page_url=dto.notion_page_url,
    )
