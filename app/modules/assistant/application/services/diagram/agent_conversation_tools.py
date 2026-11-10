"""Herramienta de lectura paginada y acotada del historial de conversación del proyecto."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    AgentConversationReader,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.shared.domain.exceptions import ForbiddenException
from app.modules.projects.domain.exceptions import ProjectNotFoundException

logger = logging.getLogger(__name__)

SEARCH_PROJECT_CONVERSATION_TOOL = AiToolDefinition(
    name="search_project_conversation",
    description=(
        "Consulta extractos del historial de conversación completada del proyecto actual. "
        "Devuelve una página acotada con cursor opaco y control estricto de presupuesto. "
        "Permite filtrar por término de búsqueda, autor ('mine' por defecto, 'project' explícito) "
        "y fecha límite 'before'. Úsalo para verificar acuerdos o decisiones previas."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": ["string", "null"],
                "minLength": 2,
                "maxLength": 120,
                "description": "Texto normalizado opcional a buscar en mensajes (2 a 120 caracteres).",
            },
            "scope": {
                "type": ["string", "null"],
                "enum": ["mine", "project", None],
                "description": "Ámbito de la búsqueda: 'mine' (por defecto) o 'project'.",
            },
            "before": {
                "type": ["string", "null"],
                "description": "Fecha límite superior exclusiva en formato ISO 8601.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Cantidad de mensajes a recuperar (1 a 5). Por defecto 5.",
            },
            "cursor": {
                "type": ["string", "null"],
                "maxLength": 256,
                "description": "Cursor opaco de paginación devuelto en una llamada anterior.",
            },
        },
        "additionalProperties": False,
    },
)

GET_PROJECT_CONVERSATION_MESSAGE_TOOL = AiToolDefinition(
    name="get_project_conversation_message",
    description=(
        "Obtiene el detalle seguro de un mensaje completado del historial por su UUID, "
        "incluyendo operaciones confirmadas en el diagrama bajo un presupuesto máximo de 4.000 caracteres."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "Identificador UUID del mensaje a consultar.",
            },
            "scope": {
                "type": ["string", "null"],
                "enum": ["mine", "project", None],
                "description": "Ámbito del mensaje: 'mine' (por defecto) o 'project'.",
            },
        },
        "required": ["message_id"],
        "additionalProperties": False,
    },
)


class AgentConversationTools:
    """Expone herramientas de consulta histórica con permisos y actor del servidor."""

    def __init__(
        self,
        conversation_reader: AgentConversationReader,
        access_policy: ProjectAccessPolicy,
        *,
        project_id: UUID,
        user_id: str,
        max_total_chars: int = 4000,
    ) -> None:
        self.conversation_reader = conversation_reader
        self.access_policy = access_policy
        self.project_id = project_id
        self.user_id = user_id
        self.max_total_chars = max(512, min(max_total_chars, 4000))

    def register(self, registry: ToolRegistry) -> None:
        registry.register(
            RegisteredTool(
                SEARCH_PROJECT_CONVERSATION_TOOL,
                self.search_project_conversation,
                mutating=False,
            )
        )
        registry.register(
            RegisteredTool(
                GET_PROJECT_CONVERSATION_MESSAGE_TOOL,
                self.get_project_conversation_message,
                mutating=False,
            )
        )

    async def search_project_conversation(
        self,
        arguments: dict[str, Any],
        _progress=None,
    ) -> dict[str, Any]:
        allowed_keys = {"query", "scope", "before", "limit", "cursor"}
        if not isinstance(arguments, dict) or set(arguments) - allowed_keys:
            raise AgentToolArgumentsException(
                "Argumentos inválidos para search_project_conversation."
            )

        raw_limit = arguments.get("limit", 5)
        if raw_limit is None:
            limit = 5
        elif (
            isinstance(raw_limit, bool)
            or not isinstance(raw_limit, int)
            or not (1 <= raw_limit <= 5)
        ):
            raise AgentToolArgumentsException(
                "El límite debe ser un entero entre 1 y 5."
            )
        else:
            limit = raw_limit

        cursor = arguments.get("cursor")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 256):
            raise AgentToolArgumentsException("Cursor inválido.")

        scope = arguments.get("scope") or "mine"
        if scope not in {"mine", "project"}:
            raise AgentToolArgumentsException("scope debe ser 'mine' o 'project'.")

        query = arguments.get("query")
        if query is not None:
            if not isinstance(query, str) or not (2 <= len(query.strip()) <= 120):
                raise AgentToolArgumentsException(
                    "query debe ser un texto de entre 2 y 120 caracteres."
                )
            query = query.strip()

        before = arguments.get("before")
        before_dt = None
        if before is not None:
            if not isinstance(before, str):
                raise AgentToolArgumentsException("before debe ser una fecha ISO 8601 válida.")
            try:
                before_dt = datetime.fromisoformat(before)
            except Exception as exc:
                raise AgentToolArgumentsException("before debe ser una fecha ISO 8601 válida.") from exc

        # Validación de autorización en cada llamada con actor del servidor
        try:
            self.access_policy.ensure_read_access(self.project_id, self.user_id)
        except (ProjectNotFoundException, ForbiddenException):
            return {"status": "forbidden", "error_code": "forbidden"}
        except Exception:
            return {"status": "forbidden", "error_code": "forbidden"}

        target_user_id = self.user_id if scope == "mine" else None

        try:
            page = self.conversation_reader.read_conversation_page(
                project_id=self.project_id,
                user_id=target_user_id,
                query=query,
                before=before_dt,
                limit=limit,
                cursor=cursor,
                max_total_chars=self.max_total_chars,
            )
        except ValueError as exc:
            raise AgentToolArgumentsException(str(exc)) from exc
        except Exception as exc:
            logger.error(
                "Fallo al leer conversación del proyecto (project_id=%s, error=%s)",
                self.project_id,
                exc,
            )
            return {"status": "unavailable", "error_code": "unavailable"}

        return {
            "status": "ok",
            "items": [
                {
                    "message_id": str(item.message_id),
                    "created_at": item.created_at,
                    "author": item.author,
                    "prompt_excerpt": item.prompt_excerpt,
                    "response_excerpt": item.response_excerpt,
                    "status": item.status,
                    "outcome": item.outcome,
                }
                for item in page.items
            ],
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
            "truncated": page.truncated,
        }

    async def get_project_conversation_message(
        self,
        arguments: dict[str, Any],
        _progress=None,
    ) -> dict[str, Any]:
        allowed_keys = {"message_id", "scope"}
        if not isinstance(arguments, dict) or set(arguments) - allowed_keys:
            raise AgentToolArgumentsException(
                "Argumentos inválidos para get_project_conversation_message."
            )

        raw_id = arguments.get("message_id")
        if not raw_id:
            raise AgentToolArgumentsException("message_id es requerido.")
        try:
            message_id = UUID(str(raw_id))
        except Exception as exc:
            raise AgentToolArgumentsException("message_id debe ser un UUID válido.") from exc

        scope = arguments.get("scope") or "mine"
        if scope not in {"mine", "project"}:
            raise AgentToolArgumentsException("scope debe ser 'mine' o 'project'.")

        try:
            self.access_policy.ensure_read_access(self.project_id, self.user_id)
        except (ProjectNotFoundException, ForbiddenException):
            return {"status": "forbidden", "error_code": "forbidden"}
        except Exception:
            return {"status": "forbidden", "error_code": "forbidden"}

        target_user_id = self.user_id if scope == "mine" else None

        try:
            detail = self.conversation_reader.read_message_detail(
                project_id=self.project_id,
                message_id=message_id,
                user_id=target_user_id,
                max_total_chars=self.max_total_chars,
            )
        except Exception as exc:
            logger.error(
                "Fallo al leer detalle de mensaje (message_id=%s, error=%s)",
                message_id,
                exc,
            )
            return {"status": "unavailable", "error_code": "unavailable"}

        if detail is None:
            return {"status": "not_found"}

        return {
            "status": "ok",
            "message_id": str(detail.message_id),
            "created_at": detail.created_at,
            "author": detail.author,
            "prompt_excerpt": detail.prompt_excerpt,
            "response_excerpt": detail.response_excerpt,
            "message_status": detail.status,
            "outcome": detail.outcome,
            "confirmed_operations": list(detail.confirmed_operations),
            "truncated": detail.truncated,
        }
