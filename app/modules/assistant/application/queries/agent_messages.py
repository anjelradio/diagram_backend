from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.modules.assistant.application.ports.agent_author_name_reader import (
    AgentAuthorNameReader,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException


@dataclass(frozen=True, slots=True)
class AgentMessageRead:
    message_id: UUID
    project_id: UUID
    user_id: str
    author_name: str
    author_avatar_url: str | None
    prompt: str
    image_url: str | None
    status: str
    cancel_requested: bool
    response_markdown: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentMessagePage:
    items: list[AgentMessageRead]
    limit: int
    offset: int
    next_offset: int | None
    has_more: bool
    snapshot_at: datetime


class AgentMessagesQueryHandler:
    """Consultas del chat compartido con activo/cancelación privada por autor."""

    DEFAULT_LIMIT = 6
    MAX_LIMIT = 50

    def __init__(
        self,
        *,
        message_repository: AgentMessageRepository,
        access_policy: ProjectAccessPolicy,
        author_name_reader: AgentAuthorNameReader,
    ) -> None:
        self.message_repository = message_repository
        self.access_policy = access_policy
        self.author_name_reader = author_name_reader

    def list_messages(
        self,
        *,
        project_id: UUID,
        user_id: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        snapshot_at: datetime | None = None,
    ) -> AgentMessagePage:
        self.access_policy.ensure_read_access(project_id, user_id)
        if not 1 <= limit <= self.MAX_LIMIT or offset < 0:
            raise ValueError("La paginación del chat no es válida.")
        snapshot = snapshot_at or datetime.now(timezone.utc)
        if snapshot.tzinfo is None:
            raise ValueError("snapshot_at debe incluir zona horaria.")
        rows = self.message_repository.list_for_project(
            project_id=project_id,
            limit=limit + 1,
            offset=offset,
            snapshot_at=snapshot,
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        views = self._project(page_rows)
        return AgentMessagePage(
            items=views,
            limit=limit,
            offset=offset,
            next_offset=offset + len(page_rows) if has_more else None,
            has_more=has_more,
            snapshot_at=snapshot,
        )

    def get_active(self, *, project_id: UUID, user_id: str) -> AgentMessageRead | None:
        self.access_policy.ensure_read_access(project_id, user_id)
        message = self.message_repository.get_active_for_user(
            project_id=project_id,
            user_id=user_id,
        )
        return self._project([message])[0] if message is not None else None

    def get_message(
        self, *, project_id: UUID, user_id: str, message_id: UUID
    ) -> AgentMessageRead:
        self.access_policy.ensure_read_access(project_id, user_id)
        message = self.message_repository.find_by_id(message_id)
        if message is None or message.project_id != project_id:
            raise ProjectNotFoundException()
        return self._project([message])[0]

    def _project(self, messages: list[AgentMessage]) -> list[AgentMessageRead]:
        profiles = self.author_name_reader.find_profiles(
            {message.user_id for message in messages}
        )
        return [
            AgentMessageRead(
                message_id=message.id,
                project_id=message.project_id,
                user_id=message.user_id,
                author_name=(profiles.get(message.user_id).name or message.user_id)
                if message.user_id in profiles
                else message.user_id,
                author_avatar_url=(profiles[message.user_id].avatar_url
                                   if message.user_id in profiles else None),
                prompt=message.prompt,
                image_url=message.image_url,
                status=message.status.value,
                cancel_requested=message.cancel_requested_at is not None,
                response_markdown=message.response_markdown,
                created_at=message.created_at,
            )
            for message in messages
        ]

