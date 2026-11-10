"""Herramientas de lectura limitadas a los elementos del proyecto actual."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentComponentReservationPublisher,
    AgentReservationActivityType,
)
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
    AgentReservationEmitter,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.diagram.application.queries.diagram.agent_diagram_queries import (
    AgentDiagramQueryHandler,
    GetAgentDiagramElementQuery,
    SearchAgentDiagramQuery,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException

_SEARCH_TYPES = {"class", "attribute", "relation"}


class DiagramReadTools:
    """Registra búsqueda y detalle como funciones con esquema estricto."""

    def __init__(
        self,
        query_handler: AgentDiagramQueryHandler,
        *,
        project_id: UUID,
        user_id: str,
        message_id: UUID | None = None,
        reservation_publisher: AgentComponentReservationPublisher | None = None,
        reservation_emitter: AgentReservationEmitter | None = None,
        max_result_chars: int = 16_000,
    ) -> None:
        if max_result_chars < 512:
            raise ValueError("El límite de detalle debe ser de al menos 512 caracteres.")
        self.query_handler = query_handler
        self.project_id = project_id
        self.user_id = user_id
        self.max_result_chars = max_result_chars
        if reservation_emitter is None and reservation_publisher is not None:
            reservation_emitter = AgentReservationEmitter(
                reservation_publisher,
                project_id=project_id,
                message_id=message_id,
            )
        self.reservation_emitter = reservation_emitter

    def register(self, registry: ToolRegistry) -> None:
        registry.register(
            RegisteredTool(
                AiToolDefinition(
                    name="list_diagram_classes",
                    description="Lista todas las clases existentes actualmente en el diagrama del proyecto.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        },
                        "additionalProperties": False,
                    },
                ),
                self._list_classes,
            )
        )
        registry.register(
            RegisteredTool(
                AiToolDefinition(
                    name="search_diagram_elements",
                    description="Busca clases, atributos o relaciones por su nombre en el proyecto actual.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "maxLength": 120},
                            "types": {
                                "type": "array",
                                "items": {"type": "string", "enum": sorted(_SEARCH_TYPES)},
                                "uniqueItems": True,
                            },
                            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                            "cursor": {"type": "string", "maxLength": 128},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                self._search,
            )
        )
        registry.register(
            RegisteredTool(
                AiToolDefinition(
                    name="get_diagram_element",
                    description="Consulta una clase, atributo o relación por ID en el proyecto actual.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": sorted(_SEARCH_TYPES)},
                            "id": {"type": "string", "format": "uuid"},
                        },
                        "required": ["type", "id"],
                        "additionalProperties": False,
                    },
                ),
                self._get,
            )
        )

    async def _list_classes(self, arguments: dict[str, Any], _progress=None) -> dict[str, Any]:
        if set(arguments) - {"limit"}:
            raise AgentToolArgumentsException()
        limit = _bounded_int(arguments.get("limit", 50), minimum=1, maximum=50)
        try:
            result = self.query_handler.search(
                SearchAgentDiagramQuery(
                    project_id=self.project_id,
                    user_id=self.user_id,
                    query="",
                    types=("class",),
                    limit=limit,
                    offset=0,
                )
            )
        except ProjectNotFoundException:
            return {"status": "forbidden", "error_code": "forbidden"}
        except (TypeError, ValueError) as exc:
            raise AgentToolArgumentsException() from exc

        classes = [
            {"id": str(item.id), "name": item.name}
            for item in result.items
            if item.element_type == "class"
        ]
        return {
            "status": "ok",
            "total": len(classes),
            "classes": classes,
        }

    async def _search(self, arguments: dict[str, Any], _progress=None) -> dict[str, Any]:
        if set(arguments) - {"query", "types", "limit", "cursor"}:
            raise AgentToolArgumentsException()
        query = arguments.get("query", "")
        types = arguments.get("types", [])
        if (
            not isinstance(query, str)
            or len(query) > 120
            or not isinstance(types, list)
            or any(not isinstance(item, str) or item not in _SEARCH_TYPES for item in types)
        ):
            raise AgentToolArgumentsException()
        try:
            offset = _decode_cursor(arguments.get("cursor"))
            result = self.query_handler.search(
                SearchAgentDiagramQuery(
                    project_id=self.project_id,
                    user_id=self.user_id,
                    query=query,
                    types=tuple(types),
                    limit=_bounded_int(arguments.get("limit", 10), minimum=1, maximum=50),
                    offset=offset,
                )
            )
        except ProjectNotFoundException:
            return {"status": "forbidden", "error_code": "forbidden"}
        except (TypeError, ValueError) as exc:
            raise AgentToolArgumentsException() from exc
        ambiguous_names = set(result.ambiguous_names)
        ambiguous = any(item.name.lower() in ambiguous_names for item in result.items)
        return {
            "status": "ambiguous" if ambiguous else "ok",
            "items": [
                {
                    "type": item.element_type,
                    "id": str(item.id),
                    "name": item.name,
                    "owner_class_id": str(item.owner_class_id)
                    if item.owner_class_id
                    else None,
                }
                for item in result.items
            ],
            "has_more": result.has_more,
            "next_cursor": _encode_cursor(result.next_offset) if result.next_offset is not None else None,
            "ambiguous": ambiguous,
        }

    async def _get(self, arguments: dict[str, Any], _progress=None) -> dict[str, Any]:
        if set(arguments) != {"type", "id"}:
            raise AgentToolArgumentsException()
        element_type = arguments.get("type")
        if not isinstance(element_type, str) or element_type not in _SEARCH_TYPES or not isinstance(arguments.get("id"), str):
            raise AgentToolArgumentsException()
        try:
            element_id = UUID(arguments["id"])
        except ValueError as exc:
            raise AgentToolArgumentsException() from exc
        try:
            result = self.query_handler.get(
                GetAgentDiagramElementQuery(
                    project_id=self.project_id,
                    user_id=self.user_id,
                    element_type=element_type,
                    element_id=element_id,
                )
            )
        except ProjectNotFoundException:
            return {"status": "forbidden", "error_code": "forbidden"}
        if result is None:
            return {"status": "not_found", "error_code": "not_found"}
        if self.reservation_emitter is not None:
            if result.element_type == "class":
                await self.reservation_emitter.reserve_class(
                    result.id, AgentReservationActivityType.QUERY
                )
            elif result.element_type == "attribute":
                owner_id_str = result.details.get("class_id")
                if owner_id_str:
                    await self.reservation_emitter.reserve_class(
                        UUID(owner_id_str), AgentReservationActivityType.QUERY
                    )
            elif result.element_type == "relation":
                source_id = (
                    UUID(result.details["source_class_id"])
                    if result.details.get("source_class_id")
                    else None
                )
                target_id = (
                    UUID(result.details["target_class_id"])
                    if result.details.get("target_class_id")
                    else None
                )
                bridge_id = (
                    UUID(result.details["bridge_class_id"])
                    if result.details.get("bridge_class_id")
                    else None
                )
                await self.reservation_emitter.reserve_relation(
                    result.id,
                    AgentReservationActivityType.QUERY,
                    source_class_id=source_id,
                    target_class_id=target_id,
                    bridge_class_id=bridge_id,
                )
        response = {
            "type": result.element_type,
            "id": str(result.id),
            "name": result.name,
            "detail": result.details,
        }
        return _bound_detail_response(response, self.max_result_chars)


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError("Entero fuera de rango")
    return value


def _encode_cursor(offset: int | None) -> str:
    if offset is None:
        return ""
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(value: Any) -> int:
    if value is None:
        return 0
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("Cursor inválido")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
        offset = int(decoded)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Cursor inválido") from exc
    return _bounded_int(offset, minimum=0, maximum=500)


def _bound_detail_response(response: dict[str, Any], maximum_chars: int) -> dict[str, Any]:
    """Reduce arrays from a large detail before it can consume model context."""
    detail = response["detail"]
    if response["type"] == "class":
        relations = detail.get("relations", [])
        attributes = detail.get("attributes", [])
        while _serialized_length(response) > maximum_chars and relations:
            relations.pop()
            detail["relations_truncated"] = True
        while _serialized_length(response) > maximum_chars and attributes:
            attributes.pop()
            detail["attributes_truncated"] = True
    elif response["type"] == "relation":
        materialization = detail.get("materialization", {})
        derived_attributes = materialization.get("derived_attributes", [])
        while _serialized_length(response) > maximum_chars and derived_attributes:
            derived_attributes.pop()
            materialization["derived_attributes_truncated"] = True

    if _serialized_length(response) <= maximum_chars:
        return response
    return {
        "type": response["type"],
        "id": response["id"],
        "name": response["name"],
        "detail": {"truncated": True},
    }


def _serialized_length(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
