"""Registro cerrado de funciones que pueden proponerse desde el modelo."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiToolDefinition,
)
from app.modules.assistant.domain.exceptions import (
    AgentToolArgumentsException,
    AgentToolLimitException,
    UnknownAgentToolException,
)

ProgressReporter = Callable[[dict[str, Any]], Awaitable[None]]
ToolHandler = Callable[
    [dict[str, Any], ProgressReporter | None],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
VisualScopeValidator = Callable[[dict[str, Any], dict[str, Any]], None]
ScopedToolHandler = Callable[
    [dict[str, Any], ProgressReporter | None, dict[str, Any]],
    dict[str, Any] | Awaitable[dict[str, Any]],
]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """Una herramienta con esquema público y ejecutor interno."""

    definition: AiToolDefinition
    handler: ToolHandler
    mutating: bool = False
    visual_scope_validator: VisualScopeValidator | None = None
    scoped_handler: ScopedToolHandler | None = None


@dataclass(frozen=True, slots=True)
class AgentToolActorContext:
    """Identidad y alcance fijados por servidor; nunca se leen de argumentos del modelo."""

    project_id: UUID
    user_id: str
    message_id: UUID


class ToolRegistry:
    """Expone solo herramientas explícitamente registradas y con argumentos acotados."""

    def __init__(
        self,
        *,
        max_arguments_chars: int = 12_000,
        actor_context: AgentToolActorContext | None = None,
    ) -> None:
        if max_arguments_chars <= 0:
            raise ValueError("El límite de argumentos debe ser positivo.")
        self.max_arguments_chars = max_arguments_chars
        self.actor_context = actor_context
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        name = tool.definition.name
        if not name or name in self._tools:
            raise ValueError("El nombre de herramienta está vacío o duplicado.")
        self._tools[name] = tool

    @property
    def definitions(self) -> tuple[AiToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def definitions_for_task(
        self,
        *,
        mutation_allowed: bool,
        include_history: bool = True,
    ) -> tuple[AiToolDefinition, ...]:
        def _allowed(tool: RegisteredTool) -> bool:
            if not mutation_allowed and tool.mutating:
                return False
            if not include_history and tool.definition.name in (
                "search_project_conversation",
                "get_project_conversation_message",
            ):
                return False
            return True

        return tuple(
            tool.definition
            for tool in self._tools.values()
            if _allowed(tool)
        )

    def allowed_names_for_task(
        self,
        *,
        mutation_allowed: bool,
        include_history: bool = True,
    ) -> frozenset[str]:
        def _allowed(tool: RegisteredTool) -> bool:
            if not mutation_allowed and tool.mutating:
                return False
            if not include_history and tool.definition.name in (
                "search_project_conversation",
                "get_project_conversation_message",
            ):
                return False
            return True

        return frozenset(
            name
            for name, tool in self._tools.items()
            if _allowed(tool)
        )

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        progress: ProgressReporter | None = None,
        *,
        allowed_names: frozenset[str] | None = None,
        visual_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if allowed_names is not None and name not in allowed_names:
            raise UnknownAgentToolException()
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownAgentToolException()
        if tool.mutating and visual_scope is not None:
            if tool.visual_scope_validator is None:
                raise AgentToolArgumentsException()
            tool.visual_scope_validator(arguments, visual_scope)
        if not isinstance(arguments, dict):
            raise AgentToolArgumentsException()
        try:
            encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise AgentToolArgumentsException() from exc
        if len(encoded) > self.max_arguments_chars:
            raise AgentToolLimitException()
        result = (
            tool.scoped_handler(arguments, progress, visual_scope)
            if tool.mutating and visual_scope is not None and tool.scoped_handler is not None
            else tool.handler(arguments, progress)
        )
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            raise AgentToolArgumentsException()
        return result
