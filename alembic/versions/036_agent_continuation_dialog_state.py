"""Add dialog_state column to agent_continuations.

Revision ID: 036_dialog_state_columns
Revises: 035_allow_partial_agent_messages
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_dialog_state_columns"
down_revision: Union[str, Sequence[str], None] = "035_allow_partial_agent_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_continuations") as batch_op:
        batch_op.add_column(sa.Column("dialog_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_continuations") as batch_op:
        batch_op.drop_column("dialog_state")
