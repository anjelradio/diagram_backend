"""Adaptador de actividad del agente al WebSocket de proyecto existente."""

import logging

from app.modules.assistant.application.ports.agent_activity_publisher import (
    AgentActivity,
    AgentActivityPublisher,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    connection_manager,
)

logger = logging.getLogger(__name__)


class WebSocketAgentActivityPublisher(AgentActivityPublisher):
    async def publish_activity(self, activity: AgentActivity) -> None:
        try:
            await connection_manager.broadcast_agent_message_activity(
                project_id=activity.project_id,
                message_id=activity.message_id,
                attempt_id=activity.attempt_id,
                sequence=activity.sequence,
                activity_code=activity.code.value,
                activity_type=activity.activity_type.value if activity.activity_type else None,
                occurred_at=activity.occurred_at,
            )
        except Exception:
            # La actividad es best-effort; el agente y su commit continúan.
            logger.debug(
                "No se pudo publicar actividad del agente (message_id=%s, code=%s)",
                activity.message_id,
                activity.code.value,
                exc_info=True,
            )
