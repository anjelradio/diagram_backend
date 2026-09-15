"""enforce one active agent activity per project

Revision ID: 7a8f5f6b9d21
Revises: 63101c9ee5c7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7a8f5f6b9d21"
down_revision: Union[str, Sequence[str], None] = "63101c9ee5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_agent_activities_active_project",
        "agent_activities",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("state = 'IN_PROGRESS' AND deleted_date IS NULL"),
        postgresql_where=sa.text("state = 'IN_PROGRESS' AND deleted_date IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_activities_active_project", table_name="agent_activities")
