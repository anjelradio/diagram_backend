from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
from uuid import UUID

from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import InvalidAgentMessageException


class AgentMessage:
    """Mensaje persistible enviado al asistente."""

    def __init__(
        self,
        *,
        id: UUID,
        project_id: UUID,
        user_id: str,
        prompt: str,
        image_url: str | None = None,
        response_markdown: str | None = None,
        status: AgentMessageStatus = AgentMessageStatus.QUEUED,
        plan: Any | None = None,
        plan_version: int = 0,
        request_fingerprint: str | None = None,
        cancel_requested_at: datetime | None = None,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
        lease_heartbeat_at: datetime | None = None,
        created_at: datetime | None = None,
        root_message_id: UUID | None = None,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.user_id = user_id
        self.prompt = prompt
        self.image_url = image_url
        self.response_markdown = response_markdown
        self.status = status
        self.plan = plan
        self.plan_version = plan_version
        self.request_fingerprint = request_fingerprint
        self.cancel_requested_at = cancel_requested_at
        self.lease_owner = lease_owner
        self.lease_expires_at = lease_expires_at
        self.lease_heartbeat_at = lease_heartbeat_at
        self.created_at = created_at or datetime.now(timezone.utc)
        self.root_message_id = root_message_id

    @classmethod
    def register(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        user_id: str,
        prompt: str,
        image_url: str | None = None,
        request_fingerprint: str | None = None,
        root_message_id: UUID | None = None,
    ) -> AgentMessage:
        normalized_prompt = prompt.strip() if isinstance(prompt, str) else ""
        if not normalized_prompt or len(normalized_prompt) > 10_000:
            raise InvalidAgentMessageException(
                "El prompt debe contener entre 1 y 10000 caracteres."
            )
        return cls(
            id=id,
            project_id=project_id,
            user_id=user_id,
            prompt=normalized_prompt,
            image_url=image_url,
            response_markdown=None,
            status=AgentMessageStatus.RUNNING,
            plan=None,
            request_fingerprint=request_fingerprint,
            root_message_id=root_message_id,
        )

    def queue(self) -> None:
        """Marca el mensaje recién registrado como pendiente por concurrencia."""
        if self.status is not AgentMessageStatus.RUNNING:
            raise InvalidAgentMessageException(
                "Solo un mensaje running recién registrado puede ponerse en cola."
            )
        self.status = AgentMessageStatus.QUEUED

    def complete(self, response_markdown: str) -> None:
        """Finaliza un mensaje en ejecución con Markdown no vacío."""
        self._ensure_running()
        response = response_markdown.strip() if isinstance(response_markdown, str) else ""
        if not response:
            raise InvalidAgentMessageException(
                "La respuesta del asistente no puede estar vacía."
            )
        self.response_markdown = response
        self.status = AgentMessageStatus.COMPLETED

    def partial(self, response_markdown: str) -> None:
        """Finaliza un mensaje en ejecución con resultado parcial y Markdown no vacío."""
        self._ensure_running()
        response = response_markdown.strip() if isinstance(response_markdown, str) else ""
        if not response:
            raise InvalidAgentMessageException(
                "La respuesta de resultado parcial no puede estar vacía."
            )
        self.response_markdown = response
        self.status = AgentMessageStatus.PARTIAL

    def fail(
        self,
        response_markdown: str = "No pude completar la solicitud. Inténtalo de nuevo.",
    ) -> None:
        """Marca como fallido un mensaje en ejecución con texto seguro."""
        self._ensure_running()
        response = response_markdown.strip() if isinstance(response_markdown, str) else ""
        if not response:
            raise InvalidAgentMessageException(
                "El mensaje de fallo no puede estar vacío."
            )
        self.response_markdown = response
        self.status = AgentMessageStatus.FAILED

    def cancel(self, response_markdown: str = "La ejecución se canceló.") -> None:
        self._ensure_running()
        response = response_markdown.strip() if isinstance(response_markdown, str) else ""
        if not response:
            raise InvalidAgentMessageException("La respuesta de cancelación no puede estar vacía.")
        self.response_markdown = response
        self.status = AgentMessageStatus.CANCELLED

    def _ensure_running(self) -> None:
        if self.status is not AgentMessageStatus.RUNNING:
            raise InvalidAgentMessageException(
                "Solo un mensaje running puede finalizarse."
            )
