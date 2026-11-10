"""Create project_integrations table.

Revision ID: 040_create_project_integrations
Revises: 039_create_diagram_audit_logs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "040_create_project_integrations"
down_revision: Union[str, Sequence[str], None] = "039_create_diagram_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("external_page_id", sa.String(length=128), nullable=True),
        sa.Column("external_database_id", sa.String(length=128), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_project_integrations_project_id",
        "project_integrations",
        ["project_id"],
    )
    op.create_index(
        "ix_project_integrations_project_provider",
        "project_integrations",
        ["project_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_integrations_project_provider", table_name="project_integrations")
    op.drop_index("ix_project_integrations_project_id", table_name="project_integrations")
    op.drop_table("project_integrations")
