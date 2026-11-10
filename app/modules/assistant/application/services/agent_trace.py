"""Correlación local de logs durante una ejecución del asistente."""

from contextvars import ContextVar, Token
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar, cast
from uuid import UUID

_message_id: ContextVar[str | None] = ContextVar("agent_message_id", default=None)
P = ParamSpec("P")
R = TypeVar("R")


def bind_agent_message(message_id: UUID) -> Token[str | None]:
    """Asocia el mensaje a las llamadas asíncronas ejecutadas en su contexto."""

    return _message_id.set(str(message_id))


def reset_agent_message(token: Token[str | None]) -> None:
    """Restaura el contexto anterior al terminar el procesamiento."""

    _message_id.reset(token)


def current_agent_message_id() -> str | None:
    """Devuelve el identificador correlacionable para logs de infraestructura."""

    return _message_id.get()


def trace_agent_message(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Propaga `message_id` al provider durante toda la corrutina del caso de uso."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        message_id = kwargs.get("message_id")
        if not isinstance(message_id, UUID):
            return await function(*args, **kwargs)
        token = bind_agent_message(message_id)
        try:
            return await function(*args, **kwargs)
        finally:
            reset_agent_message(token)

    return cast(Callable[P, Awaitable[R]], wrapped)
