from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.modules.integrations.domain.enums.notion_task_priority import (
    NotionTaskPriority,
)
from app.modules.integrations.domain.enums.notion_task_status import (
    NotionTaskStatus,
)


@dataclass(frozen=True, slots=True)
class NotionTaskRecord:
    """Representación inmutable de una tarea leída o creada en Notion."""

    task_id: str
    title: str
    description: str
    status: NotionTaskStatus
    priority: NotionTaskPriority
    assignee_name: str
    due_date: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class NotionProjectWelcomeContent:
    """Contenido estructurado para la bienvenida y estado del proyecto en Notion."""

    welcome_heading: str
    executive_description: str
    team_members: list[str]
    diagram_classes_summary: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class NotionInitializedWorkspace:
    """Resultado de la inicialización del espacio de Notion para un proyecto."""

    page_id: str
    database_id: str
    page_url: str


class NotionIntegrationProvider(ABC):
    """Puerto para interactuar con la API / MCP oficial de Notion."""

    @abstractmethod
    def validate_api_key(
        self,
        api_key: str,
        *,
        parent_page_id: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Valida la API key. Retorna (es_valido, parent_page_id_resuelto, workspace_name)."""

    @abstractmethod
    def initialize_project_workspace(
        self,
        *,
        api_key: str,
        parent_page_id: str,
        project_name: str,
        welcome_content: NotionProjectWelcomeContent,
    ) -> NotionInitializedWorkspace:
        """Crea la página raíz del proyecto y la base de datos de tareas en Notion."""

    @abstractmethod
    def create_task(
        self,
        *,
        api_key: str,
        database_id: str,
        title: str,
        description: str,
        assignee_name: str,
        priority: NotionTaskPriority = NotionTaskPriority.MEDIUM,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        """Crea una tarea en la base de datos de Notion asignada a un colaborador."""

    @abstractmethod
    def list_tasks(
        self,
        *,
        api_key: str,
        database_id: str,
        assignee_name: str | None = None,
        status: NotionTaskStatus | None = None,
    ) -> list[NotionTaskRecord]:
        """Consulta tareas en Notion filtradas opcionalmente por responsable y/o estado."""

    @abstractmethod
    def get_task(
        self,
        *,
        api_key: str,
        task_id: str,
    ) -> NotionTaskRecord | None:
        """Obtiene el detalle de una tarea específica en Notion."""

    @abstractmethod
    def update_task(
        self,
        *,
        api_key: str,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: NotionTaskStatus | None = None,
        priority: NotionTaskPriority | None = None,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        """Actualiza propiedades de una tarea en Notion."""

    @abstractmethod
    def delete_task(
        self,
        *,
        api_key: str,
        task_id: str,
    ) -> bool:
        """Archiva/elimina una tarea en Notion."""
