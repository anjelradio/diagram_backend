from typing import Protocol
from datetime import datetime
from uuid import UUID


class AgentCompletionPublisher(Protocol):
    """Puerto opcional para notificar el cierre terminal del mensaje a los clientes."""

    async def publish_finished(
        self, *, project_id: UUID, user_id: str, message_id: UUID, prompt: str,
        image_url: str | None, status: str, response_markdown: str, created_at: datetime,
        author_name: str | None = None, author_avatar_url: str | None = None,
    ) -> None:
        """Publica la proyección terminal del mensaje tras confirmar la transacción."""
        ...
