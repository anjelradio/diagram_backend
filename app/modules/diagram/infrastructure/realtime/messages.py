"""Contrato tipado de mensajes intercambiados por el WebSocket del diagrama."""

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class PingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"]


class CursorMoveMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cursor_move"]
    x: float
    y: float


class ClassDragMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["class_drag"]
    class_id: UUID
    x: float
    y: float


class ClassLockAcquireMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["class_lock_acquire"]
    class_id: UUID


class ClassLockReleaseMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["class_lock_release"]
    class_id: UUID


ClientIncomingMessage = Annotated[
    Union[
        PingMessage,
        CursorMoveMessage,
        ClassDragMessage,
        ClassLockAcquireMessage,
        ClassLockReleaseMessage,
    ],
    Field(discriminator="type"),
]

client_message_adapter = TypeAdapter(ClientIncomingMessage)


def parse_client_message(payload: object) -> ClientIncomingMessage:
    """Valida un mensaje JSON del navegador y rechaza campos desconocidos."""
    return client_message_adapter.validate_python(payload)


def presence_snapshot(
    sessions: list[dict[str, object]],
    locks: list[dict[str, object]],
    agent_lock: dict[str, str] | None = None,
) -> dict[str, object]:
    """Construye el mensaje de presencia inicial de una sala."""
    return {"type": "presence_snapshot", "peers": sessions, "class_locks": locks, "agent_lock": agent_lock}


def diagram_mutation(operation_type: str, data: dict[str, object], sender_id: str) -> dict[str, object]:
    """Construye un evento de mutación persistida para los clientes remotos."""
    return {
        "type": "diagram_mutation",
        "operation_type": operation_type,
        "data": data,
        "sender_id": sender_id,
    }
