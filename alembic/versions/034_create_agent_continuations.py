"""Create agent continuations table.

Revision ID: 034_create_agent_continuations
Revises: 033_agent_msg_durable_execution
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034_create_agent_continuations"
down_revision: Union[str, Sequence[str], None] = "033_agent_msg_durable_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_continuations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("root_message_id", sa.Uuid(), nullable=False),
        sa.Column("latest_message_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_request", sa.String(length=10000), nullable=False),
        sa.Column("resolved_facts", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False, server_default="awaiting_input"),
        sa.Column("source_plan_message_id", sa.Uuid(), nullable=True),
        sa.Column("recent_message_ids", sa.JSON(), nullable=False),
        sa.Column("image_context", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_message_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "state IN ('awaiting_input', 'ready', 'claimed', 'resolved', 'declined', 'expired')",
            name="ck_agent_continuations_state",
        ),
        sa.CheckConstraint(
            "outcome IN ('awaiting_input', 'partial', 'success', 'technical_failure')",
            name="ck_agent_continuations_outcome",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["root_message_id"], ["agent_messages.id"]),
        sa.ForeignKeyConstraint(["latest_message_id"], ["agent_messages.id"]),
        sa.ForeignKeyConstraint(["source_plan_message_id"], ["agent_messages.id"]),
        sa.ForeignKeyConstraint(["claimed_by_message_id"], ["agent_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_continuations_project_id", "agent_continuations", ["project_id"])
    op.create_index("ix_agent_continuations_user_id", "agent_continuations", ["user_id"])
    op.create_index("ix_agent_continuations_root_message_id", "agent_continuations", ["root_message_id"])
    op.create_index("ix_agent_continuations_latest_message_id", "agent_continuations", ["latest_message_id"])
    op.create_index("ix_agent_continuations_state", "agent_continuations", ["state"])
    op.create_index("ix_agent_continuations_expires_at", "agent_continuations", ["expires_at"])
    op.create_index("ix_agent_continuations_claimed_by_message_id", "agent_continuations", ["claimed_by_message_id"])
    op.create_index(
        "ix_agent_continuations_project_user", "agent_continuations", ["project_id", "user_id"]
    )
    op.create_index(
        "ix_agent_continuations_root_msg", "agent_continuations", ["root_message_id"]
    )
    op.create_index(
        "ix_agent_continuations_active",
        "agent_continuations",
        ["project_id", "user_id", "state", "expires_at"],
        sqlite_where=sa.text("deleted_date IS NULL"),
        postgresql_where=sa.text("deleted_date IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_continuations_active", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_root_msg", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_project_user", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_claimed_by_message_id", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_expires_at", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_state", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_latest_message_id", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_root_message_id", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_user_id", table_name="agent_continuations")
    op.drop_index("ix_agent_continuations_project_id", table_name="agent_continuations")
    op.drop_table("agent_continuations")
