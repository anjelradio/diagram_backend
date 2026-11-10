"""Allow partial status in agent_messages check constraint.

Revision ID: 035_allow_partial_agent_messages
Revises: 034_create_agent_continuations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "035_allow_partial_agent_messages"
down_revision: Union[str, Sequence[str], None] = "034_create_agent_continuations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.drop_constraint("ck_agent_messages_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_messages_status",
            "status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.drop_constraint("ck_agent_messages_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_messages_status",
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
        )
