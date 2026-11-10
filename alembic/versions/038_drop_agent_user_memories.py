"""Drop agent_user_memories table.

Revision ID: 038_drop_agent_user_memories
Revises: 037_agent_request_threads
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "038_drop_agent_user_memories"
down_revision: Union[str, Sequence[str], None] = "037_agent_request_threads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop agent_user_memories table and indexes."""
    try:
        op.drop_index("uq_agent_user_memories_active_project_user", table_name="agent_user_memories", if_exists=True)
    except Exception:
        pass

    try:
        op.drop_index("ix_agent_user_memories_project_id", table_name="agent_user_memories", if_exists=True)
    except Exception:
        pass

    try:
        op.drop_index("ix_agent_user_memories_user_id", table_name="agent_user_memories", if_exists=True)
    except Exception:
        pass

    op.drop_table("agent_user_memories")


def downgrade() -> None:
    """Recreate agent_user_memories table and indexes if rolled back."""
    op.create_table(
        "agent_user_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("summary_context", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_user_memories_user_id", "agent_user_memories", ["user_id"])
    op.create_index(
        "ix_agent_user_memories_project_id", "agent_user_memories", ["project_id"]
    )
    op.create_index(
        "uq_agent_user_memories_active_project_user",
        "agent_user_memories",
        ["project_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("deleted_date IS NULL"),
        postgresql_where=sa.text("deleted_date IS NULL"),
    )
