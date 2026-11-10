import uuid
from typing import Any
from sqlalchemy import Column, Index, JSON, String, Text
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class ProjectIntegrationModel(BaseModel, table=True):
    """Modelo de base de datos para integraciones de proyectos (Notion, Neon)."""

    __tablename__ = "project_integrations"
    __table_args__ = (
        Index("ix_project_integrations_project_provider", "project_id", "provider"),
    )

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    provider: str = Field(
        sa_column=Column(String(32), nullable=False),
    )
    encrypted_api_key: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    external_page_id: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    external_database_id: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    config_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default={}),
    )
