from sqlmodel import Field
from app.shared.infrastructure.db.base_model import BaseModel


class ProjectModel(BaseModel, table=True):
    """Modelo de persistencia para proyectos."""

    __tablename__ = "projects"

    owner_id: str = Field(index=True, nullable=False)
    name: str = Field(nullable=False, max_length=255)
    description: str | None = Field(default=None, nullable=True)
    thumbnail_url: str | None = Field(default=None, nullable=True)
