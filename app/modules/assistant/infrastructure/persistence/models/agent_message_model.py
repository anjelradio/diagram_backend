from typing import Any
from uuid import UUID

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Index, Integer, JSON, String, text
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class AgentMessageModel(BaseModel, table=True):
    """Fila persistida de mensajes del asistente."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_agent_messages_status",
        ),
        Index(
            "uq_agent_messages_running_project_user",
            "project_id",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'running' AND deleted_date IS NULL"),
            postgresql_where=text("status = 'running' AND deleted_date IS NULL"),
        ),
        Index("ix_agent_messages_project_user", "project_id", "user_id"),
        Index("ix_agent_messages_root_msg", "root_message_id"),
    )

    project_id: UUID = Field(foreign_key="projects.id", nullable=False, index=True)
    user_id: str = Field(nullable=False, index=True)
    root_message_id: UUID | None = Field(
        default=None, foreign_key="agent_messages.id", nullable=True, index=True
    )
    prompt: str = Field(nullable=False, max_length=10_000)
    image_url: str | None = Field(default=None, max_length=2048)
    response_markdown: str | None = Field(default=None)
    status: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    plan: Any | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    plan_version: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    request_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    cancel_requested_at: datetime | None = Field(default=None, index=True)
    lease_owner: str | None = Field(default=None, max_length=100)
    lease_expires_at: datetime | None = Field(default=None, index=True)
    lease_heartbeat_at: datetime | None = Field(default=None)
