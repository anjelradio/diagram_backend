import uuid
from sqlalchemy import Column, String, UniqueConstraint
from sqlmodel import Field
from app.shared.infrastructure.db.base_model import BaseModel
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus


class ProjectMemberModel(BaseModel, table=True):
    """Modelo de persistencia para participantes de proyectos."""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
    )

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        index=True,
        nullable=False,
    )
    user_id: str = Field(index=True, nullable=False)
    role: ProjectMemberRole = Field(
        sa_column=Column(String(20), nullable=False, default=ProjectMemberRole.READER.value)
    )
    status: ProjectMemberStatus = Field(
        sa_column=Column(String(20), nullable=False, default=ProjectMemberStatus.ACTIVE.value)
    )
