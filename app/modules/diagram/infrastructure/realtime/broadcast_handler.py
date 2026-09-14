"""Puente del bus sincrónico de dominio hacia las salas WebSocket."""

import asyncio
import logging

from app.modules.diagram.domain.events.diagram_events import DiagramMutationEvent

from .connection_manager import connection_manager

logger = logging.getLogger(__name__)
_event_loop: asyncio.AbstractEventLoop | None = None


def configure_broadcast_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda el loop ASGI que debe recibir los broadcasts post-commit."""
    global _event_loop
    _event_loop = loop


class WebSocketBroadcastEventHandler:
    """Convierte un evento de dominio en un mensaje JSON para una sala."""

    def handle(self, event: DiagramMutationEvent) -> None:
        if _event_loop is None or _event_loop.is_closed():
            logger.debug("Broadcast omitido: no hay loop ASGI activo")
            return
        payload = {
            "type": "diagram_mutation",
            "operation_type": event.operation_type,
            "data": event.data,
            "sender_id": event.sender_id,
        }
        asyncio.run_coroutine_threadsafe(
            connection_manager.broadcast(
                event.project_id,
                payload,
                exclude_user_id=event.sender_id,
            ),
            _event_loop,
        )


websocket_broadcast_handler = WebSocketBroadcastEventHandler()
