from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Protocol


class ModelRole(str, Enum):
    """Propósito de una inferencia sin acoplarlo al proveedor concreto."""

    MAIN = "main"
    VISION = "vision"
    PLANNING = "planning"
    EXECUTION = "execution"
    COMPACTION = "compaction"


@dataclass(frozen=True, slots=True)
class AiContentPart:
    """Parte textual o visual de un mensaje multimodal."""

    type: Literal["text", "image_url"]
    text: str | None = None
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class AiMessage:
    """Mensaje de conversación independiente del formato HTTP del proveedor."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | tuple[AiContentPart, ...]
    tool_calls: tuple["AiToolCall", ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class AiToolDefinition:
    """Definición neutral de una herramienta de función ofrecida al modelo."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AiToolCall:
    """Llamada propuesta por el proveedor; la aplicación debe validarla."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AiRequest:
    """Solicitud de inferencia de aplicación."""

    model_role: ModelRole
    messages: tuple[AiMessage, ...]
    purpose: str = "unspecified"
    max_output_tokens: int = 2048
    tools: tuple[AiToolDefinition, ...] = ()
    response_format: Literal["text", "json_object"] = "text"
    enable_reasoning: bool | None = None


@dataclass(frozen=True, slots=True)
class AiResult:
    """Respuesta de texto y telemetría opcional reportada por el proveedor."""

    text: str
    model_role: ModelRole
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    duration_ms: float | None = None
    tool_calls: tuple[AiToolCall, ...] = ()
    completed: bool = True
    metadata: dict[str, Any] | None = None


class AiProvider(Protocol):
    """Puerto de inferencia asíncrono consumido por los servicios del agente."""

    async def complete(self, request: AiRequest) -> AiResult:
        """Genera texto para una secuencia tipada de mensajes."""
        ...
