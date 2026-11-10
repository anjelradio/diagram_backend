from typing import Any
import uuid

from sqlalchemy import Column, Index, JSON, String
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class DiagramAuditLogModel(BaseModel, table=True):
    """Modelo de base de datos para eventos de bitácora y auditoría de diagrama."""

    __tablename__ = "diagram_audit_logs"
    __table_args__ = (
        Index("ix_diagram_audit_logs_project_created", "project_id", "created_date"),
        Index(
            "ix_diagram_audit_logs_project_user_created",
            "project_id",
            "user_id",
            "created_date",
        ),
        Index(
            "ix_diagram_audit_logs_project_entity",
            "project_id",
            "entity_type",
            "entity_id",
        ),
    )

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
    )
    user_id: str = Field(
        sa_column=Column(String(255), nullable=False, index=True)
    )
    user_name: str = Field(
        sa_column=Column(String(255), nullable=False)
    )
    actor_type: str = Field(
        sa_column=Column(String(20), nullable=False, index=True)
    )
    entity_type: str = Field(
        sa_column=Column(String(20), nullable=False, index=True)
    )
    entity_id: uuid.UUID = Field(
        nullable=False,
        index=True,
    )
    entity_name: str = Field(
        sa_column=Column(String(255), nullable=False)
    )
    parent_class_id: uuid.UUID | None = Field(
        default=None,
        nullable=True,
        index=True,
    )
    parent_class_name: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    action: str = Field(
        sa_column=Column(String(20), nullable=False, index=True)
    )
    use_case: str = Field(
        sa_column=Column(String(100), nullable=False, index=True)
    )
    summary: str = Field(
        sa_column=Column(String(1000), nullable=False)
    )
    payload_before: Any | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    payload_after: Any | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
