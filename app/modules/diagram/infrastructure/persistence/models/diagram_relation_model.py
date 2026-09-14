import uuid
from sqlalchemy import CheckConstraint, Column, Index, String
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class DiagramRelationModel(BaseModel, table=True):
    """Modelo de base de datos para relaciones UML entre clases de diagrama."""

    __tablename__ = "diagram_relations"
    __table_args__ = (
        CheckConstraint(
            "source_class_id != target_class_id",
            name="ck_diagram_relations_no_self_reference",
        ),
        CheckConstraint(
            "(relation_type = 'ASSOCIATION' AND source_cardinality IS NOT NULL AND target_cardinality IS NOT NULL) "
            "OR (relation_type != 'ASSOCIATION' AND source_cardinality IS NULL AND target_cardinality IS NULL)",
            name="ck_diagram_relations_cardinality_consistency",
        ),
        CheckConstraint(
            "(bridge_class_id IS NULL AND bridge_handle IS NULL) "
            "OR (bridge_class_id IS NOT NULL AND bridge_handle IS NOT NULL)",
            name="ck_diagram_relations_bridge_consistency",
        ),
        CheckConstraint(
            "relation_type IN ('ASSOCIATION', 'AGGREGATION', 'COMPOSITION', 'GENERALIZATION', 'REALIZATION', 'DEPENDENCY')",
            name="ck_diagram_relations_type_enum",
        ),
        CheckConstraint(
            "source_cardinality IS NULL OR source_cardinality IN ('0..1', '1', '0..*', '1..*')",
            name="ck_diagram_relations_src_cardinality_enum",
        ),
        CheckConstraint(
            "target_cardinality IS NULL OR target_cardinality IN ('0..1', '1', '0..*', '1..*')",
            name="ck_diagram_relations_tgt_cardinality_enum",
        ),
        CheckConstraint(
            "source_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name="ck_diagram_relations_src_handle_enum",
        ),
        CheckConstraint(
            "target_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name="ck_diagram_relations_tgt_handle_enum",
        ),
        CheckConstraint(
            "bridge_handle IS NULL OR bridge_handle IN ('TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT', 'RIGHT_TOP', 'RIGHT_CENTER', 'RIGHT_BOTTOM', "
            "'BOTTOM_RIGHT', 'BOTTOM_CENTER', 'BOTTOM_LEFT', 'LEFT_BOTTOM', 'LEFT_CENTER', 'LEFT_TOP')",
            name="ck_diagram_relations_bridge_handle_enum",
        ),
        Index("ix_diagram_relations_project_id", "project_id"),
        Index("ix_diagram_relations_source_class_id", "source_class_id"),
        Index("ix_diagram_relations_target_class_id", "target_class_id"),
        Index("ix_diagram_relations_bridge_class_id", "bridge_class_id"),
    )

    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        ondelete="CASCADE",
    )
    source_class_id: uuid.UUID = Field(
        foreign_key="diagram_classes.id",
        nullable=False,
        ondelete="CASCADE",
    )
    target_class_id: uuid.UUID = Field(
        foreign_key="diagram_classes.id",
        nullable=False,
        ondelete="CASCADE",
    )
    name: str = Field(
        default="Nueva relación",
        sa_column=Column(String(255), nullable=False),
    )
    relation_type: str = Field(
        sa_column=Column(String(50), nullable=False),
    )
    source_cardinality: str | None = Field(
        default=None,
        sa_column=Column(String(20), nullable=True),
    )
    target_cardinality: str | None = Field(
        default=None,
        sa_column=Column(String(20), nullable=True),
    )
    source_handle: str = Field(
        sa_column=Column(String(50), nullable=False),
    )
    target_handle: str = Field(
        sa_column=Column(String(50), nullable=False),
    )
    bridge_class_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="diagram_classes.id",
        nullable=True,
        ondelete="SET NULL",
    )
    bridge_handle: str | None = Field(
        default=None,
        sa_column=Column(String(50), nullable=True),
    )
