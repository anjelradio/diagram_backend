"""Adaptador de reservas de componentes del agente sobre el WebSocket de proyecto existente."""

import logging
from uuid import UUID

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentComponentReservationEvent,
    AgentComponentReservationPublisher,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    connection_manager,
)

logger = logging.getLogger(__name__)


class WebSocketAgentComponentReservationPublisher(AgentComponentReservationPublisher):
    async def publish_reservation(self, event: AgentComponentReservationEvent) -> None:
        try:
            await connection_manager.broadcast_agent_component_reserved(
                project_id=event.project_id,
                message_id=event.message_id,
                sequence=event.sequence,
                component_type=event.component_type.value,
                component_id=event.component_id,
                activity_type=event.activity_type.value,
                attribute_id=event.attribute_id,
            )
        except Exception:
            logger.debug(
                "No se pudo publicar reserva de componente (message_id=%s, component_id=%s)",
                event.message_id,
                event.component_id,
                exc_info=True,
            )

    async def publish_release(self, project_id: UUID, message_id: UUID) -> None:
        try:
            await connection_manager.broadcast_agent_component_reservations_released(
                project_id=project_id,
                message_id=message_id,
            )
        except Exception:
            logger.debug(
                "No se pudo publicar liberación de reservas (message_id=%s)",
                message_id,
                exc_info=True,
            )

    def publish_release_sync(self, project_id: UUID, message_id: UUID) -> None:
        try:
            room = connection_manager.rooms.get(project_id)
            if room is not None:
                room.release_message_reservations(message_id)
            try:
                import anyio
                anyio.from_thread.run(self.publish_release, project_id, message_id)
            except Exception:
                try:
                    import anyio
                    anyio.run(self.publish_release, project_id, message_id)
                except Exception:
                    pass
        except Exception:
            logger.debug(
                "No se pudo publicar liberación de reservas sincrónica (message_id=%s)",
                message_id,
                exc_info=True,
            )

