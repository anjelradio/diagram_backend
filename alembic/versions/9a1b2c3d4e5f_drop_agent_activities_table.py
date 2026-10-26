"""drop agent_activities table

Revision ID: 9a1b2c3d4e5f
Revises: 8b42b33b905c
Create Date: 2026-10-25 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9a1b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = '8b42b33b905c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop agent_activities table and indexes."""
    try:
        op.drop_index("uq_agent_activities_active_project", table_name="agent_activities", if_exists=True)
    except Exception:
        pass

    try:
        op.drop_index(op.f("ix_agent_activities_project_id"), table_name="agent_activities", if_exists=True)
    except Exception:
        pass

    op.drop_table("agent_activities")


def downgrade() -> None:
    """Recreate agent_activities table if rolled back."""
    op.create_table(
        'agent_activities',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('modified_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('transcription', sa.Text(), nullable=True),
        sa.Column('resume', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=1024), nullable=True),
        sa.Column('state', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_activities_project_id'), 'agent_activities', ['project_id'], unique=False)
