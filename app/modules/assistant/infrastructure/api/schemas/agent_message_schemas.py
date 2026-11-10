from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    project_id: UUID
    user_id: str
    author_name: str
    author_avatar_url: str | None = None
    prompt: str
    image_url: str | None
    status: str
    cancel_requested: bool
    response_markdown: str | None
    created_at: datetime


class AgentMessagePageRead(BaseModel):
    items: list[AgentMessageRead]
    limit: int
    offset: int
    next_offset: int | None
    has_more: bool
    snapshot_at: datetime


class AgentMessageActiveRead(BaseModel):
    message: AgentMessageRead | None


class AgentMessageCreatedRead(BaseModel):
    """Proyección persistida de aceptación de un mensaje del asistente."""

    message_id: UUID
    project_id: UUID
    status: str
    image_url: str | None
    prompt: str
    user_id: str
    author_name: str
    author_avatar_url: str | None = None
    cancel_requested: bool = False
    created_at: datetime
    response_markdown: str | None = None
