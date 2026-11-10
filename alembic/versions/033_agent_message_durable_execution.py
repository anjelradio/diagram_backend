"""Add fingerprint, cancellation signal, and worker lease to assistant messages."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033_agent_msg_durable_execution"
down_revision: Union[str, Sequence[str], None] = "032_agent_message_plan_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_messages", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("agent_messages", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_messages", sa.Column("lease_owner", sa.String(length=100), nullable=True))
    op.add_column("agent_messages", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_messages", sa.Column("lease_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_agent_messages_request_fingerprint", "agent_messages", ["request_fingerprint"])
    op.create_index("ix_agent_messages_cancel_requested_at", "agent_messages", ["cancel_requested_at"])
    op.create_index("ix_agent_messages_lease_expires_at", "agent_messages", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_lease_expires_at", table_name="agent_messages")
    op.drop_index("ix_agent_messages_cancel_requested_at", table_name="agent_messages")
    op.drop_index("ix_agent_messages_request_fingerprint", table_name="agent_messages")
    op.drop_column("agent_messages", "lease_heartbeat_at")
    op.drop_column("agent_messages", "lease_expires_at")
    op.drop_column("agent_messages", "lease_owner")
    op.drop_column("agent_messages", "cancel_requested_at")
    op.drop_column("agent_messages", "request_fingerprint")
