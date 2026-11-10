"""Emite etapas efímeras correlacionadas con un intento del worker."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from app.modules.assistant.application.ports.agent_activity_publisher import (
    AgentActivity,
    AgentActivityCode,
    AgentActivityPublisher,
)


class AgentActivityReporter:
    def __init__(
        self,
        publisher: AgentActivityPublisher,
        *,
        project_id: UUID,
        message_id: UUID,
        attempt_id: UUID,
        stopped: asyncio.Event | None = None,
    ) -> None:
        self._publisher = publisher
        self._project_id = project_id
        self._message_id = message_id
        self._attempt_id = attempt_id
        self._stopped = stopped
        self._sequence = 0

    async def report(self, code: AgentActivityCode) -> None:
        if self._stopped is not None and self._stopped.is_set():
            return
        self._sequence += 1
        await self._publisher.publish_activity(
            AgentActivity(
                project_id=self._project_id,
                message_id=self._message_id,
                attempt_id=self._attempt_id,
                sequence=self._sequence,
                code=code,
                occurred_at=datetime.now(timezone.utc),
            )
        )
