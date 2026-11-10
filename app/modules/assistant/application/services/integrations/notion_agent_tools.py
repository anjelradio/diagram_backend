from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition
from app.modules.assistant.application.services.execution.tool_registry import (
    ProgressReporter,
    RegisteredTool,
    ToolRegistry,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionIntegrationProvider,
    NotionTaskRecord,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.enums.notion_task_priority import (
    NotionTaskPriority,
)
from app.modules.integrations.domain.enums.notion_task_status import (
    NotionTaskStatus,
)
from app.modules.integrations.domain.exceptions import (
    NotionIntegrationNotConfiguredException,
    NotionProjectNotInitializedException,
    NotionTaskNotFoundException,
    NotionTaskOwnershipException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)

logger = logging.getLogger(__name__)


class NotionAgentTools:
    """Herramientas del asistente para gestionar tareas en Notion con aislamiento por usuario."""

    def __init__(
        self,
        *,
        project_id: UUID,
        current_user_name: str,
        integration_repository: ProjectIntegrationRepository,
        crypto_service: IntegrationCryptoService,
        notion_provider: NotionIntegrationProvider,
    ) -> None:
        self.project_id = project_id
        self.current_user_name = current_user_name.strip() or "Colaborador"
        self.integration_repository = integration_repository
        self.crypto_service = crypto_service
        self.notion_provider = notion_provider

    def _get_active_integration_context(self) -> tuple[str, str]:
        """Obtiene y valida la API Key descifrada y el database_id de tareas del proyecto."""
        integration = self.integration_repository.find_by_project_and_provider(
            self.project_id,
            IntegrationProvider.NOTION,
        )
        if integration is None or not integration.encrypted_api_key:
            raise NotionIntegrationNotConfiguredException()
        if not integration.is_initialized or not integration.external_database_id:
            raise NotionProjectNotInitializedException()

        api_key = self.crypto_service.decrypt(integration.encrypted_api_key)
        database_id = integration.external_database_id
        return api_key, database_id

    def register(self, registry: ToolRegistry) -> None:
        """Registra las 4 herramientas de tareas de Notion en el ToolRegistry."""
        registry.register(
            RegisteredTool(
                definition=AiToolDefinition(
                    name="list_notion_tasks",
                    description=(
                        "Consulta las tareas u observaciones en Notion del proyecto pertenecientes exclusivamente al usuario actual. "
                        "Permite saber qué tareas pendientes o hechas tiene asignadas."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["Pendiente", "En progreso", "Done", "ALL"],
                                "description": "Filtro opcional. Por defecto devuelve las pendientes ('Pendiente'). Usa 'ALL' para ver todas o 'Done' para ver las terminadas.",
                            }
                        },
                        "additionalProperties": False,
                    },
                ),
                handler=self._list_tasks,
                mutating=False,
            )
        )

        registry.register(
            RegisteredTool(
                definition=AiToolDefinition(
                    name="create_notion_task",
                    description=(
                        "Crea una nueva tarea o apunte en la base de datos de Notion del proyecto asignada automáticamente al nombre del usuario actual. "
                        "Puede usarse tanto para órdenes directas como para recapitular sugerencias/mejoras que el asistente dio en el turno anterior."
                    ),
                    parameters={
                        "type": "object",
                        "required": ["title"],
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Título conciso y claro de la tarea.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detalle o especificaciones de la tarea (incluyendo sugerencias previas si aplica).",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["Alta", "Media", "Baja"],
                                "description": "Prioridad de la tarea (por defecto 'Media').",
                            },
                            "due_date": {
                                "type": "string",
                                "description": "Fecha opcional en formato YYYY-MM-DD.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ),
                handler=self._create_task,
                mutating=True,
            )
        )

        registry.register(
            RegisteredTool(
                definition=AiToolDefinition(
                    name="update_notion_task",
                    description=(
                        "Actualiza el estado ('Pendiente', 'En progreso', 'Done'), título o descripción de una tarea de Notion. "
                        "Valida estrictamente que la tarea pertenezca al usuario actual antes de modificarla."
                    ),
                    parameters={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "ID de la tarea en Notion.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["Pendiente", "En progreso", "Done"],
                                "description": "Nuevo estado de la tarea.",
                            },
                            "title": {
                                "type": "string",
                                "description": "Nuevo título opcional.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Nueva descripción opcional.",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["Alta", "Media", "Baja"],
                            },
                            "due_date": {
                                "type": "string",
                                "description": "Fecha en formato YYYY-MM-DD o vacío para remover.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ),
                handler=self._update_task,
                mutating=True,
            )
        )

        registry.register(
            RegisteredTool(
                definition=AiToolDefinition(
                    name="delete_notion_task",
                    description=(
                        "Elimina (archiva) una tarea existente en Notion. "
                        "Valida estrictamente que la tarea pertenezca al usuario actual antes de eliminarla."
                    ),
                    parameters={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "ID de la tarea en Notion a eliminar.",
                            }
                        },
                        "additionalProperties": False,
                    },
                ),
                handler=self._delete_task,
                mutating=True,
            )
        )

    async def _list_tasks(
        self,
        arguments: dict[str, Any],
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        api_key, database_id = self._get_active_integration_context()
        raw_status = arguments.get("status")
        filter_status = None
        if raw_status and raw_status != "ALL":
            filter_status = NotionTaskStatus.from_raw(raw_status)
        elif raw_status is None:
            # Por defecto listar pendientes
            filter_status = NotionTaskStatus.PENDING

        tasks = self.notion_provider.list_tasks(
            api_key=api_key,
            database_id=database_id,
            assignee_name=self.current_user_name,
            status=filter_status,
        )

        serialized_tasks = [
            {
                "index": idx + 1,
                "task_id": t.task_id,
                "title": t.title,
                "description": t.description,
                "status": t.status.value,
                "priority": t.priority.value,
                "due_date": t.due_date,
            }
            for idx, t in enumerate(tasks)
        ]

        return {
            "status": "ok",
            "assignee": self.current_user_name,
            "tasks_count": len(serialized_tasks),
            "tasks": serialized_tasks,
        }

    async def _create_task(
        self,
        arguments: dict[str, Any],
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        api_key, database_id = self._get_active_integration_context()
        title = arguments.get("title", "").strip()
        description = arguments.get("description", "").strip()
        priority = NotionTaskPriority.from_raw(arguments.get("priority"))
        due_date = arguments.get("due_date")

        task = self.notion_provider.create_task(
            api_key=api_key,
            database_id=database_id,
            title=title,
            description=description,
            assignee_name=self.current_user_name,
            priority=priority,
            due_date=due_date,
        )

        return {
            "status": "applied",
            "task": {
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "status": task.status.value,
                "priority": task.priority.value,
                "assignee": task.assignee_name,
                "due_date": task.due_date,
                "url": task.url,
            },
        }

    def _resolve_task_id(self, api_key: str, database_id: str, raw_task_id: str) -> str:
        clean = raw_task_id.strip()
        if len(clean.replace("-", "")) == 32:
            return clean

        ordinal_map = {
            "primera": 0, "primero": 0, "primer": 0, "1": 0, "1ra": 0, "1ro": 0, "1era": 0, "1ero": 0,
            "segunda": 1, "segundo": 1, "2": 1, "2da": 1, "2do": 1,
            "tercera": 2, "tercero": 2, "tercer": 2, "3": 2, "3ra": 2, "3ro": 2,
            "cuarta": 3, "cuarto": 3, "4": 3, "4ta": 3, "4to": 3,
            "quinta": 4, "quinto": 4, "5": 4, "5ta": 4, "5to": 4,
            "última": -1, "ultima": -1, "último": -1, "ultimo": -1,
        }

        try:
            tasks = self.notion_provider.list_tasks(
                api_key=api_key,
                database_id=database_id,
                assignee_name=self.current_user_name,
            )
            if not tasks:
                tasks = self.notion_provider.list_tasks(
                    api_key=api_key,
                    database_id=database_id,
                )

            clean_lower = clean.casefold()
            for ord_word, ord_idx in ordinal_map.items():
                if re.search(r"\b" + re.escape(ord_word) + r"\b", clean_lower):
                    idx = ord_idx if ord_idx >= 0 else len(tasks) - 1
                    if 0 <= idx < len(tasks):
                        return tasks[idx].task_id

            num_match = re.search(r"\b(?:tarea\s+)?(\d+)\b", clean_lower)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(tasks):
                    return tasks[idx].task_id

            for t in tasks:
                if clean_lower in t.title.casefold() or t.title.casefold() in clean_lower:
                    return t.task_id
        except Exception as exc:
            logger.warning("No se pudo resolver dinámicamente task_id=%s: %s", raw_task_id, exc)

        return clean

    async def _update_task(
        self,
        arguments: dict[str, Any],
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        api_key, database_id = self._get_active_integration_context()
        raw_task_id = arguments.get("task_id", "").strip()
        task_id = self._resolve_task_id(api_key, database_id, raw_task_id)

        # Validar propiedad
        existing = self.notion_provider.get_task(api_key=api_key, task_id=task_id)
        if existing is None:
            raise NotionTaskNotFoundException()
        if existing.assignee_name != self.current_user_name:
            raise NotionTaskOwnershipException()

        status = NotionTaskStatus.from_raw(arguments.get("status")) if arguments.get("status") else None
        priority = NotionTaskPriority.from_raw(arguments.get("priority")) if arguments.get("priority") else None
        title = arguments.get("title")
        description = arguments.get("description")
        due_date = arguments.get("due_date")

        updated = self.notion_provider.update_task(
            api_key=api_key,
            task_id=task_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            due_date=due_date,
        )

        return {
            "status": "applied",
            "task": {
                "task_id": updated.task_id,
                "title": updated.title,
                "status": updated.status.value,
                "priority": updated.priority.value,
                "assignee": updated.assignee_name,
            },
        }

    async def _delete_task(
        self,
        arguments: dict[str, Any],
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        api_key, database_id = self._get_active_integration_context()
        raw_task_id = arguments.get("task_id", "").strip()
        task_id = self._resolve_task_id(api_key, database_id, raw_task_id)

        # Validar propiedad
        existing = self.notion_provider.get_task(api_key=api_key, task_id=task_id)
        if existing is None:
            raise NotionTaskNotFoundException()
        if existing.assignee_name != self.current_user_name:
            raise NotionTaskOwnershipException()

        deleted = self.notion_provider.delete_task(api_key=api_key, task_id=task_id)
        return {
            "status": "applied" if deleted else "not_found",
            "task_id": task_id,
            "deleted": deleted,
        }
