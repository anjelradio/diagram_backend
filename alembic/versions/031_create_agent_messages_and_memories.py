"""Create assistant message and user memory tables.

Revision ID: 031_agent_msgs_memories
Revises: 9a1b2c3d4e5f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "031_agent_msgs_memories"
down_revision: Union[str, Sequence[str], None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("prompt", sa.String(length=10000), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("response_markdown", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_messages_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_messages_project_id", "agent_messages", ["project_id"])
    op.create_index("ix_agent_messages_user_id", "agent_messages", ["user_id"])
    op.create_index("ix_agent_messages_status", "agent_messages", ["status"])
    op.create_index(
        "ix_agent_messages_project_user", "agent_messages", ["project_id", "user_id"]
    )
    op.create_index(
        "uq_agent_messages_running_project_user",
        "agent_messages",
        ["project_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running' AND deleted_date IS NULL"),
        postgresql_where=sa.text("status = 'running' AND deleted_date IS NULL"),
    )

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


def downgrade() -> None:
    op.drop_index("uq_agent_user_memories_active_project_user", table_name="agent_user_memories")
    op.drop_index("ix_agent_user_memories_project_id", table_name="agent_user_memories")
    op.drop_index("ix_agent_user_memories_user_id", table_name="agent_user_memories")
    op.drop_table("agent_user_memories")
    op.drop_index("uq_agent_messages_running_project_user", table_name="agent_messages")
    op.drop_index("ix_agent_messages_project_user", table_name="agent_messages")
    op.drop_index("ix_agent_messages_status", table_name="agent_messages")
    op.drop_index("ix_agent_messages_user_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_project_id", table_name="agent_messages")
    op.drop_table("agent_messages")
