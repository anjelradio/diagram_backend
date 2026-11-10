"""Add optimistic versioning for agent execution plan progress."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "032_agent_message_plan_version"
down_revision: Union[str, Sequence[str], None] = "031_agent_msgs_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_messages",
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_messages", "plan_version")
