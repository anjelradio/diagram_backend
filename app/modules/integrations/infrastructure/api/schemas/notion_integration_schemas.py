from uuid import UUID
from pydantic import BaseModel, Field


class ConfigureNotionIntegrationRequest(BaseModel):
    """Payload para configurar la API Key de Notion."""

    api_key: str = Field(..., min_length=1, description="Token de integración interna de Notion (ntn_...)")
    parent_page_id: str | None = Field(default=None, description="ID opcional de la página contenedora en Notion")


class InitializeNotionProjectRequest(BaseModel):
    """Payload para inicializar el proyecto en Notion."""

    description: str = Field(..., min_length=1, description="Breve descripción del propósito del proyecto")


class NotionIntegrationStatusRead(BaseModel):
    """Esquema de respuesta para el estado de la integración de Notion."""

    project_id: UUID
    provider: str
    has_api_key: bool
    is_initialized: bool
    notion_page_id: str | None = None
    notion_tasks_database_id: str | None = None
    notion_page_url: str | None = None
