"""allow_diagram_relation_self_reference

Revision ID: 8b42b33b905c
Revises: 7a8f5f6b9d21
Create Date: 2026-09-22 22:06:39.105531

"""
from typing import Sequence, Union
import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b42b33b905c'
down_revision: Union[str, Sequence[str], None] = '7a8f5f6b9d21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to allow self-referencing diagram relations for associations with distinct handles."""
    with op.batch_alter_table("diagram_relations") as batch_op:
        batch_op.drop_constraint("ck_diagram_relations_no_self_reference", type_="check")
        batch_op.create_check_constraint(
            "ck_diagram_relations_self_reference_rule",
            "(source_class_id != target_class_id) OR (relation_type = 'ASSOCIATION' AND source_handle != target_handle)"
        )


def downgrade() -> None:
    """Downgrade schema to disallow self-referencing diagram relations."""
    with op.batch_alter_table("diagram_relations") as batch_op:
        batch_op.drop_constraint("ck_diagram_relations_self_reference_rule", type_="check")
        batch_op.create_check_constraint(
            "ck_diagram_relations_no_self_reference",
            "source_class_id != target_class_id"
        )
