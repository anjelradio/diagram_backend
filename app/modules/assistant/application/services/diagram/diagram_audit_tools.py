"""Herramientas del asistente para consulta de auditoría y bitácora de cambios."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.services.audit.audit_query_service import (
    AuditQueryResult,
    AuditQueryService,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException

logger = logging.getLogger(__name__)

_VALID_TIME_FILTERS = {
    "today", "hoy",
    "yesterday", "ayer",
    "day_before_yesterday", "anteayer", "antes_de_ayer", "antes de ayer",
    "recent_days", "ultimos_dias", "últimos_días", "ultimos dias", "últimos días",
    "this_week", "esta_semana", "esta semana", "semana",
}
_VALID_ENTITY_TYPES = {"CLASS", "ATTRIBUTE", "RELATION"}
_VALID_ACTIONS = {"CREATE", "UPDATE", "DELETE"}


class DiagramAuditTools:
    """Registra la herramienta query_diagram_audit_logs en el ToolRegistry."""

    def __init__(
        self,
        audit_query_service: AuditQueryService,
        *,
        project_id: UUID,
        user_id: str,
        user_timezone: str | None = None,
    ) -> None:
        self.audit_query_service = audit_query_service
        self.project_id = project_id
        self.user_id = user_id
        self.user_timezone = user_timezone or "America/La_Paz"

    def register(self, registry: ToolRegistry) -> None:
        registry.register(
            RegisteredTool(
                AiToolDefinition(
                    name="query_diagram_audit_logs",
                    description=(
                        "Consulta el historial de auditoría y bitácora de cambios del diagrama UML del proyecto. "
                        "Permite buscar por nombre de colaborador, nombre de clase, nombre de atributo, acción o rango de fechas."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "collaborator_name": {
                                "type": "string",
                                "description": "Nombre o fragmento del nombre del colaborador a buscar (ej: 'Juan', 'Carlos').",
                            },
                            "entity_name": {
                                "type": "string",
                                "description": "Nombre de la clase o atributo buscado (ej: 'Producto', 'stock').",
                            },
                            "parent_class_name": {
                                "type": "string",
                                "description": "Nombre de la clase contenedora cuando se busca un atributo o relación (ej: 'Pedido').",
                            },
                            "entity_type": {
                                "type": "string",
                                "enum": ["CLASS", "ATTRIBUTE", "RELATION"],
                                "description": "Tipo de elemento modificado.",
                            },
                            "action": {
                                "type": "string",
                                "enum": ["CREATE", "UPDATE", "DELETE"],
                                "description": "Tipo de acción ejecutada.",
                            },
                            "time_filter": {
                                "type": "string",
                                "enum": ["today", "yesterday", "day_before_yesterday", "recent_days", "this_week"],
                                "description": "Ventana de tiempo relativa.",
                            },
                            "exact_date": {
                                "type": "string",
                                "description": "Fecha específica en formato YYYY-MM-DD.",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "Zona horaria del usuario para interpretar fechas relativas y presentar horas (ej: 'America/La_Paz'). Por defecto 'America/La_Paz'.",
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "description": "Límite de eventos a recuperar (por defecto 50).",
                            },
                        },
                        "additionalProperties": False,
                    },
                ),
                self._query_audit_logs,
                mutating=False,
            )
        )

    async def _query_audit_logs(
        self,
        arguments: dict[str, Any],
        _progress=None,
    ) -> dict[str, Any]:
        """Ejecuta la consulta estructurada en la bitácora de auditoría."""
        # Validar argumentos no permitidos
        allowed_keys = {
            "collaborator_name",
            "entity_name",
            "parent_class_name",
            "entity_type",
            "action",
            "time_filter",
            "exact_date",
            "timezone",
            "limit",
        }
        if set(arguments) - allowed_keys:
            raise AgentToolArgumentsException()

        collaborator_name = arguments.get("collaborator_name")
        if collaborator_name is not None and not isinstance(collaborator_name, str):
            raise AgentToolArgumentsException()

        entity_name = arguments.get("entity_name")
        if entity_name is not None and not isinstance(entity_name, str):
            raise AgentToolArgumentsException()

        parent_class_name = arguments.get("parent_class_name")
        if parent_class_name is not None and not isinstance(parent_class_name, str):
            raise AgentToolArgumentsException()

        entity_type = arguments.get("entity_type")
        if entity_type is not None:
            if not isinstance(entity_type, str) or entity_type.upper() not in _VALID_ENTITY_TYPES:
                raise AgentToolArgumentsException()
            entity_type = entity_type.upper()

        action = arguments.get("action")
        if action is not None:
            if not isinstance(action, str) or action.upper() not in _VALID_ACTIONS:
                raise AgentToolArgumentsException()
            action = action.upper()

        time_filter = arguments.get("time_filter")
        if time_filter is not None:
            if not isinstance(time_filter, str) or time_filter.lower() not in _VALID_TIME_FILTERS:
                raise AgentToolArgumentsException()
            time_filter = time_filter.lower()

        exact_date = arguments.get("exact_date")
        if exact_date is not None and not isinstance(exact_date, str):
            raise AgentToolArgumentsException()

        tz_arg = arguments.get("timezone")
        if tz_arg is not None and not isinstance(tz_arg, str):
            raise AgentToolArgumentsException()
        target_timezone = tz_arg or self.user_timezone

        limit = arguments.get("limit", 50)
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise AgentToolArgumentsException()

        result: AuditQueryResult = self.audit_query_service.execute_query(
            project_id=self.project_id,
            collaborator_name=collaborator_name,
            entity_name=entity_name,
            parent_class_name=parent_class_name,
            entity_type=entity_type,
            action=action,
            time_filter=time_filter,
            exact_date=exact_date,
            limit=limit,
            user_timezone=target_timezone,
        )

        response: dict[str, Any] = {
            "status": "success",
            "total_events": result.total_events,
            "time_range": result.time_range_label,
            "timezone": result.timezone,
            "timezone_label": result.timezone_label,
            "collaborators_matched": result.collaborators_matched,
            "grouped_by_date": result.grouped_by_date,
            "events_sample": result.events[:15],
        }

        if result.is_ambiguous_collaborator:
            response["ambiguity"] = result.ambiguity_message

        if result.total_events == 0:
            msg = "No se encontraron registros de modificaciones en el historial para los criterios especificados."
            if collaborator_name:
                msg = f"No se encontraron registros de modificaciones realizadas por {collaborator_name} en el período indicado."
            elif entity_name:
                msg = f"No se encontraron registros históricos para el elemento '{entity_name}'."
            response["message"] = msg

        return response
