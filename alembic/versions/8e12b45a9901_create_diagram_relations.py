"""create_diagram_relations

Revision ID: 8e12b45a9901
Revises: 4c29f039a654
Create Date: 2026-09-13 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e12b45a9901'
down_revision: Union[str, Sequence[str], None] = '4c29f039a654'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include diagram_relations and FK metadata."""
    op.create_table(
        'diagram_relations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('modified_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('source_class_id', sa.Uuid(), nullable=False),
        sa.Column('target_class_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('relation_type', sa.String(length=50), nullable=False),
        sa.Column('source_cardinality', sa.String(length=20), nullable=True),
        sa.Column('target_cardinality', sa.String(length=20), nullable=True),
        sa.Column('source_handle', sa.String(length=50), nullable=False),
        sa.Column('target_handle', sa.String(length=50), nullable=False),
        sa.Column('bridge_class_id', sa.Uuid(), nullable=True),
        sa.Column('bridge_handle', sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            'source_class_id != target_class_id',
            name='ck_diagram_relations_no_self_reference'
        ),
        sa.CheckConstraint(
            "(relation_type = 'ASSOCIATION' AND source_cardinality IS NOT NULL AND target_cardinality IS NOT NULL) "
            "OR (relation_type != 'ASSOCIATION' AND source_cardinality IS NULL AND target_cardinality IS NULL)",
            name='ck_diagram_relations_cardinality_consistency'
        ),
        sa.CheckConstraint(
            "(bridge_class_id IS NULL AND bridge_handle IS NULL) "
            "OR (bridge_class_id IS NOT NULL AND bridge_handle IS NOT NULL)",
            name='ck_diagram_relations_bridge_consistency'
        ),
        sa.CheckConstraint(
            "relation_type IN ('ASSOCIATION', 'AGGREGATION', 'COMPOSITION', 'GENERALIZATION', 'REALIZATION', 'DEPENDENCY')",
            name='ck_diagram_relations_type_enum'
        ),
        sa.CheckConstraint(
            "source_cardinality IS NULL OR source_cardinality IN ('0..1', '1', '0..*', '1..*')",
            name='ck_diagram_relations_src_cardinality_enum'
        ),
        sa.CheckConstraint(
            "target_cardinality IS NULL OR target_cardinality IN ('0..1', '1', '0..*', '1..*')",
            name='ck_diagram_relations_tgt_cardinality_enum'
        ),
        sa.CheckConstraint(
            "source_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name='ck_diagram_relations_src_handle_enum'
        ),
        sa.CheckConstraint(
            "target_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name='ck_diagram_relations_tgt_handle_enum'
        ),
        sa.CheckConstraint(
            "bridge_handle IS NULL OR bridge_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name='ck_diagram_relations_bridge_handle_enum'
        ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_class_id'], ['diagram_classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_class_id'], ['diagram_classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bridge_class_id'], ['diagram_classes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_diagram_relations_project_id'), 'diagram_relations', ['project_id'], unique=False)
    op.create_index(op.f('ix_diagram_relations_source_class_id'), 'diagram_relations', ['source_class_id'], unique=False)
    op.create_index(op.f('ix_diagram_relations_target_class_id'), 'diagram_relations', ['target_class_id'], unique=False)
    op.create_index(op.f('ix_diagram_relations_bridge_class_id'), 'diagram_relations', ['bridge_class_id'], unique=False)

    # Añadir columnas y restricciones FK en diagram_attributes
    with op.batch_alter_table('diagram_attributes') as batch_op:
        batch_op.add_column(sa.Column('is_foreign_key', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        batch_op.add_column(sa.Column('referenced_class_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('relation_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_diagram_attributes_referenced_class_id'), ['referenced_class_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_diagram_attributes_relation_id'), ['relation_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_diagram_attributes_referenced_class_id',
            'diagram_classes',
            ['referenced_class_id'],
            ['id'],
            ondelete='CASCADE'
        )
        batch_op.create_foreign_key(
            'fk_diagram_attributes_relation_id',
            'diagram_relations',
            ['relation_id'],
            ['id'],
            ondelete='CASCADE'
        )
        batch_op.create_check_constraint(
            'ck_diagram_attributes_fk_invariants',
            "(NOT is_foreign_key AND referenced_class_id IS NULL AND relation_id IS NULL) "
            "OR (is_foreign_key AND referenced_class_id IS NOT NULL AND relation_id IS NOT NULL AND data_type = 'UUID')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('diagram_attributes') as batch_op:
        batch_op.drop_constraint('ck_diagram_attributes_fk_invariants', type_='check')
        batch_op.drop_constraint('fk_diagram_attributes_relation_id', type_='foreignkey')
        batch_op.drop_constraint('fk_diagram_attributes_referenced_class_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_diagram_attributes_relation_id'))
        batch_op.drop_index(batch_op.f('ix_diagram_attributes_referenced_class_id'))
        batch_op.drop_column('relation_id')
        batch_op.drop_column('referenced_class_id')
        batch_op.drop_column('is_foreign_key')

    op.drop_index(op.f('ix_diagram_relations_bridge_class_id'), table_name='diagram_relations')
    op.drop_index(op.f('ix_diagram_relations_target_class_id'), table_name='diagram_relations')
    op.drop_index(op.f('ix_diagram_relations_source_class_id'), table_name='diagram_relations')
    op.drop_index(op.f('ix_diagram_relations_project_id'), table_name='diagram_relations')
    op.drop_table('diagram_relations')
