"""Create diagram_audit_logs table.

Revision ID: 039_create_diagram_audit_logs
Revises: 038_drop_agent_user_memories
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "039_create_diagram_audit_logs"
down_revision: Union[str, Sequence[str], None] = "038_drop_agent_user_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diagram_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entity_name", sa.String(length=255), nullable=False),
        sa.Column("parent_class_id", sa.Uuid(), nullable=True),
        sa.Column("parent_class_name", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("use_case", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("payload_before", sa.JSON(), nullable=True),
        sa.Column("payload_after", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_diagram_audit_logs_project_id", "diagram_audit_logs", ["project_id"])
    op.create_index("ix_diagram_audit_logs_user_id", "diagram_audit_logs", ["user_id"])
    op.create_index("ix_diagram_audit_logs_actor_type", "diagram_audit_logs", ["actor_type"])
    op.create_index("ix_diagram_audit_logs_entity_type", "diagram_audit_logs", ["entity_type"])
    op.create_index("ix_diagram_audit_logs_entity_id", "diagram_audit_logs", ["entity_id"])
    op.create_index("ix_diagram_audit_logs_parent_class_id", "diagram_audit_logs", ["parent_class_id"])
    op.create_index("ix_diagram_audit_logs_action", "diagram_audit_logs", ["action"])
    op.create_index("ix_diagram_audit_logs_use_case", "diagram_audit_logs", ["use_case"])
    op.create_index(
        "ix_diagram_audit_logs_project_created",
        "diagram_audit_logs",
        ["project_id", "created_date"],
    )
    op.create_index(
        "ix_diagram_audit_logs_project_user_created",
        "diagram_audit_logs",
        ["project_id", "user_id", "created_date"],
    )
    op.create_index(
        "ix_diagram_audit_logs_project_entity",
        "diagram_audit_logs",
        ["project_id", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_diagram_audit_logs_project_entity", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_project_user_created", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_project_created", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_use_case", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_action", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_parent_class_id", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_entity_id", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_entity_type", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_actor_type", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_user_id", table_name="diagram_audit_logs")
    op.drop_index("ix_diagram_audit_logs_project_id", table_name="diagram_audit_logs")
    op.drop_table("diagram_audit_logs")
