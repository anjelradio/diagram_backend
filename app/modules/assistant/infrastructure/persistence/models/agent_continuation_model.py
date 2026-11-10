"""Modelo de base de datos para la entidad de continuación conversacional."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, JSON, String, text
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class AgentContinuationModel(BaseModel, table=True):
    """Fila persistida que conserva el estado de solicitudes del agente."""

    __tablename__ = "agent_continuations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('awaiting_input', 'ready', 'claimed', 'resolved', 'declined', 'expired')",
            name="ck_agent_continuations_state",
        ),
        CheckConstraint(
            "outcome IN ('awaiting_input', 'partial', 'success', 'technical_failure')",
            name="ck_agent_continuations_outcome",
        ),
        CheckConstraint(
            "purpose IN ('clarification', 'residual_retry')",
            name="ck_agent_continuations_purpose",
        ),
        Index(
            "uq_agent_continuations_active_scope",
            "project_id",
            "user_id",
            unique=True,
            sqlite_where=text("deleted_date IS NULL AND purpose = 'clarification' AND state IN ('awaiting_input', 'ready', 'claimed')"),
            postgresql_where=text("deleted_date IS NULL AND purpose = 'clarification' AND state IN ('awaiting_input', 'ready', 'claimed')"),
        ),
        Index(
            "ix_agent_continuations_active",
            "project_id",
            "user_id",
            "state",
            "expires_at",
            sqlite_where=text("deleted_date IS NULL"),
            postgresql_where=text("deleted_date IS NULL"),
        ),
        Index("ix_agent_continuations_project_user", "project_id", "user_id"),
        Index("ix_agent_continuations_root_msg", "root_message_id"),
    )

    project_id: UUID = Field(foreign_key="projects.id", nullable=False, index=True)
    user_id: str = Field(nullable=False, index=True)
    root_message_id: UUID = Field(foreign_key="agent_messages.id", nullable=False, index=True)
    latest_message_id: UUID = Field(foreign_key="agent_messages.id", nullable=False, index=True)
    state: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    effective_request: str = Field(nullable=False, max_length=10_000)
    resolved_facts: Any = Field(default=[], sa_column=Column(JSON, nullable=False))
    missing_fields: Any = Field(default=[], sa_column=Column(JSON, nullable=False))
    outcome: str = Field(sa_column=Column(String(30), nullable=False, default="awaiting_input"))
    purpose: str = Field(
        default="clarification",
        sa_column=Column(String(30), nullable=False, server_default="clarification"),
    )
    close_reason: str | None = Field(
        default=None,
        sa_column=Column(String(50), nullable=True),
    )
    source_plan_message_id: UUID | None = Field(
        default=None, foreign_key="agent_messages.id", nullable=True
    )
    recent_message_ids: Any = Field(default=[], sa_column=Column(JSON, nullable=False))
    image_context: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    dialog_state: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    claimed_by_message_id: UUID | None = Field(
        default=None, foreign_key="agent_messages.id", nullable=True, index=True
    )
