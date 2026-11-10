from datetime import datetime
from uuid import UUID

from app.modules.assistant.application.ports.agent_completion_publisher import (
    AgentCompletionPublisher,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    connection_manager,
)


class WebSocketAgentCompletionPublisher(AgentCompletionPublisher):
    """Emite la proyección persistida del mensaje tras confirmar estado terminal."""

    async def publish_finished(
        self,
        *,
        project_id: UUID,
        user_id: str,
        message_id: UUID,
        prompt: str,
        image_url: str | None,
        status: str,
        response_markdown: str,
        created_at: datetime,
        author_name: str | None = None,
        author_avatar_url: str | None = None,
    ) -> None:
        await connection_manager.broadcast_agent_message_finished(
            project_id=project_id,
            user_id=user_id,
            message_id=message_id,
            prompt=prompt,
            image_url=image_url,
            status=status,
            response_markdown=response_markdown,
            created_at=created_at,
            author_name=author_name,
            author_avatar_url=author_avatar_url,
        )
        try:
            await connection_manager.broadcast_agent_component_reservations_released(
                project_id=project_id,
                message_id=message_id,
            )
        except Exception:
            pass

