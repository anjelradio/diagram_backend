"""Add agent request threads, purpose, close_reason and scope uniqueness.

Revision ID: 037_agent_request_threads
Revises: 036_dialog_state_columns
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037_agent_request_threads"
down_revision: Union[str, Sequence[str], None] = "036_dialog_state_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar root_message_id a agent_messages
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.add_column(sa.Column("root_message_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_agent_messages_root_msg", ["root_message_id"])

    # 2. Agregar purpose y close_reason a agent_continuations
    with op.batch_alter_table("agent_continuations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "purpose",
                sa.String(length=30),
                nullable=False,
                server_default="clarification",
            )
        )
        batch_op.add_column(
            sa.Column("close_reason", sa.String(length=50), nullable=True)
        )

    # 3. Sanear datos heredados para unicidad parcial
    connection = op.get_bind()

    # Clasificar posibles residual retries heredados
    connection.execute(
        sa.text(
            """
            UPDATE agent_continuations
            SET purpose = 'residual_retry'
            WHERE source_plan_message_id IS NOT NULL
              AND (
                CAST(resolved_facts AS TEXT) = '[]'
                OR resolved_facts IS NULL
              )
            """
        )
    )

    # Sanear reclamos huérfanos: continuaciones claimed cuyo mensaje reclamante ya terminó o no existe
    connection.execute(
        sa.text(
            """
            UPDATE agent_continuations
            SET state = 'expired', close_reason = 'orphan_claim_cleared'
            WHERE state = 'claimed'
              AND (
                claimed_by_message_id IS NULL
                OR claimed_by_message_id IN (
                    SELECT id FROM agent_messages WHERE status IN ('completed', 'failed', 'cancelled')
                )
                OR claimed_by_message_id NOT IN (
                    SELECT id FROM agent_messages
                )
              )
            """
        )
    )

    # Resolver duplicados en estado activo (awaiting_input, ready, claimed)
    # Selecciona solo el más reciente por (project_id, user_id) y expira los demás
    duplicates_query = sa.text(
        """
        SELECT id, project_id, user_id, modified_date, created_date
        FROM agent_continuations
        WHERE deleted_date IS NULL
          AND purpose = 'clarification'
          AND state IN ('awaiting_input', 'ready', 'claimed')
        ORDER BY project_id, user_id, modified_date DESC, created_date DESC, id DESC
        """
    )
    rows = connection.execute(duplicates_query).fetchall()

    seen_scopes: set[tuple[str, str]] = set()
    to_expire_ids: list[str] = []

    for row in rows:
        scope = (str(row.project_id), str(row.user_id))
        if scope in seen_scopes:
            to_expire_ids.append(str(row.id))
        else:
            seen_scopes.add(scope)

    for cont_id in to_expire_ids:
        connection.execute(
            sa.text(
                """
                UPDATE agent_continuations
                SET state = 'expired', close_reason = 'expired'
                WHERE id = :id
                """
            ),
            {"id": cont_id},
        )

    # 4. Crear restricciones e índice parcial único
    with op.batch_alter_table("agent_continuations") as batch_op:
        batch_op.create_check_constraint(
            "ck_agent_continuations_purpose",
            "purpose IN ('clarification', 'residual_retry')",
        )
        batch_op.create_index(
            "uq_agent_continuations_active_scope",
            ["project_id", "user_id"],
            unique=True,
            sqlite_where=sa.text(
                "deleted_date IS NULL AND purpose = 'clarification' AND state IN ('awaiting_input', 'ready', 'claimed')"
            ),
            postgresql_where=sa.text(
                "deleted_date IS NULL AND purpose = 'clarification' AND state IN ('awaiting_input', 'ready', 'claimed')"
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_continuations") as batch_op:
        batch_op.drop_index("uq_agent_continuations_active_scope")
        batch_op.drop_constraint("ck_agent_continuations_purpose", type_="check")
        batch_op.drop_column("close_reason")
        batch_op.drop_column("purpose")

    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.drop_index("ix_agent_messages_root_msg")
        batch_op.drop_column("root_message_id")
