import uuid
from sqlalchemy import Column, Float, String
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class DiagramClassModel(BaseModel, table=True):
    """Modelo de base de datos para clases de diagrama."""

    __tablename__ = "diagram_classes"

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        index=True,
        nullable=False,
    )
    name: str = Field(
        sa_column=Column(String(255), nullable=False)
    )
    position_x: float = Field(
        sa_column=Column(Float, nullable=False)
    )
    position_y: float = Field(
        sa_column=Column(Float, nullable=False)
    )
