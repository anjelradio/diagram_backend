from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class AgentUserMemoryModel(BaseModel, table=True):
    """Resumen de contexto futuro de un usuario dentro de un proyecto."""

    __tablename__ = "agent_user_memories"
    __table_args__ = (
        Index(
            "uq_agent_user_memories_active_project_user",
            "project_id",
            "user_id",
            unique=True,
            sqlite_where=text("deleted_date IS NULL"),
            postgresql_where=text("deleted_date IS NULL"),
        ),
    )

    user_id: str = Field(nullable=False, index=True)
    project_id: UUID = Field(foreign_key="projects.id", nullable=False, index=True)
    summary_context: str = Field(nullable=False)
