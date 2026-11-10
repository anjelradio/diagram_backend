"""Adaptador de aceptación persistida al WebSocket de la sala del proyecto."""

import logging
from datetime import datetime
from uuid import UUID

from app.modules.assistant.application.ports.agent_acceptance_publisher import (
    AgentAcceptancePublisher,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    connection_manager,
)

logger = logging.getLogger(__name__)


class WebSocketAgentAcceptancePublisher(AgentAcceptancePublisher):
    async def publish_accepted(
        self,
        *,
        project_id: UUID,
        message_id: UUID,
        user_id: str,
        author_name: str,
        author_avatar_url: str | None,
        prompt: str,
        image_url: str | None,
        status: str,
        cancel_requested: bool,
        response_markdown: str | None,
        created_at: datetime,
    ) -> None:
        try:
            await connection_manager.broadcast_agent_message_accepted(
                project_id=project_id,
                message_id=message_id,
                user_id=user_id,
                author_name=author_name,
                author_avatar_url=author_avatar_url,
                prompt=prompt,
                image_url=image_url,
                status=status,
                cancel_requested=cancel_requested,
                response_markdown=response_markdown,
                created_at=created_at,
            )
        except Exception:
            logger.debug(
                "No se pudo publicar aceptación del agente (message_id=%s)",
                message_id,
                exc_info=True,
            )
