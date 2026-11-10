"""Add thumbnail_updated_at to projects table.

Revision ID: 041_project_thumbnail_updated
Revises: 040_create_project_integrations
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "041_project_thumbnail_updated"
down_revision: Union[str, Sequence[str], None] = "040_create_project_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("thumbnail_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "thumbnail_updated_at")
