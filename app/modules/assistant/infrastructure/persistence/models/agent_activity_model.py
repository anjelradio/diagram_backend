import uuid
from sqlalchemy import Column, Index, String, Text, text
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class AgentActivityModel(BaseModel, table=True):
    """Modelo de base de datos para registrar actividades del asistente IA."""

    __tablename__ = "agent_activities"

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        index=True,
        nullable=False,
    )
    transcription: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    resume: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    image_url: str | None = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True),
    )
    state: str = Field(
        default="IN_PROGRESS",
        sa_column=Column(String(50), nullable=False),
    )

    # La base de datos evita dos ejecuciones activas incluso bajo concurrencia.
    __table_args__ = (
        Index(
            "uq_agent_activities_active_project",
            "project_id",
            unique=True,
            sqlite_where=text("state = 'IN_PROGRESS' AND deleted_date IS NULL"),
            postgresql_where=text("state = 'IN_PROGRESS' AND deleted_date IS NULL"),
        ),
    )
