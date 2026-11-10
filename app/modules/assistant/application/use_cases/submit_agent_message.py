"""Acepta el mensaje y despierta el ejecutor después del commit de creación."""

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.assistant.application.use_cases.create_agent_message import (
    CreateAgentMessageCommand,
    CreateAgentMessageUseCase,
    CreatedAgentMessage,
)
from app.modules.assistant.application.ports.agent_acceptance_publisher import (
    AgentAcceptancePublisher,
)

logger = logging.getLogger(__name__)


class AgentMessageDispatcher(Protocol):
    def notify(self, message_id: UUID) -> None:
        """Despierta un worker; el mensaje ya fue confirmado en persistencia."""


@dataclass(frozen=True, slots=True)
class SubmittedAgentMessage:
    message: CreatedAgentMessage


class SubmitAgentMessageUseCase:
    """Separación explícita entre aceptar en HTTP y ejecutar en background."""

    def __init__(
        self,
        *,
        create_message: CreateAgentMessageUseCase,
        dispatcher: AgentMessageDispatcher,
        acceptance_publisher: AgentAcceptancePublisher | None = None,
    ) -> None:
        self.create_message = create_message
        self.dispatcher = dispatcher
        self.acceptance_publisher = acceptance_publisher

    async def execute(
        self,
        command: CreateAgentMessageCommand,
        *,
        author_name: str | None = None,
        author_avatar_url: str | None = None,
    ) -> SubmittedAgentMessage:
        message = await self.create_message.execute(command)
        if self.acceptance_publisher is not None and not message.was_existing:
            try:
                await self.acceptance_publisher.publish_accepted(
                    project_id=message.project_id,
                    message_id=message.message_id,
                    user_id=message.user_id,
                    author_name=author_name or message.user_id,
                    author_avatar_url=author_avatar_url,
                    prompt=message.prompt,
                    image_url=message.image_url,
                    status=message.status,
                    cancel_requested=message.cancel_requested,
                    response_markdown=message.response_markdown,
                    created_at=message.created_at,
                )
            except Exception:
                # GET history repairs a missed ephemeral event; acceptance is durable.
                logger.exception("No se pudo difundir la aceptación de %s", message.message_id)
        try:
            self.dispatcher.notify(message.message_id)
        except Exception:
            # El poller recupera el registro confirmado aunque falle el wake-up.
            logger.exception("No se pudo despertar el worker para %s", message.message_id)
        return SubmittedAgentMessage(message=message)

