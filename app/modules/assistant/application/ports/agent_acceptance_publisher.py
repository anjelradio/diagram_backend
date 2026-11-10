"""Puerto para anunciar que un mensaje del agente quedó persistido y aceptado."""

from datetime import datetime
from typing import Protocol
from uuid import UUID


class AgentAcceptancePublisher(Protocol):
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
        """Difunde la proyección confirmada después del commit."""
        ...
