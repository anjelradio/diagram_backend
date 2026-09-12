import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime
from sqlmodel import Field
from app.shared.infrastructure.db.base_model import BaseModel


class InvitationModel(BaseModel, table=True):
    """Modelo de persistencia para invitaciones temporales de proyectos."""

    __tablename__ = "invitations"

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        unique=True,
        index=True,
        nullable=False,
    )
    code: str = Field(
        unique=True,
        index=True,
        nullable=False,
        max_length=10,
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
