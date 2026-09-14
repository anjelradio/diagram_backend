import uuid
from sqlalchemy import Boolean, Column, Integer, String, UniqueConstraint, CheckConstraint
from sqlmodel import Field

from app.shared.infrastructure.db.base_model import BaseModel


class DiagramAttributeModel(BaseModel, table=True):
    """Modelo de base de datos para atributos de clases de diagrama."""

    __tablename__ = "diagram_attributes"
    __table_args__ = (
        UniqueConstraint("class_id", "position", name="uq_diagram_attributes_class_position"),
        CheckConstraint(
            "(NOT is_primary_key) OR (position = 0 AND data_type = 'UUID' AND NOT is_nullable)",
            name="ck_diagram_attributes_pk_invariants",
        ),
        CheckConstraint(
            "is_primary_key OR (position >= 1)",
            name="ck_diagram_attributes_sec_position",
        ),
        CheckConstraint(
            "(NOT is_foreign_key AND referenced_class_id IS NULL AND relation_id IS NULL) "
            "OR (is_foreign_key AND referenced_class_id IS NOT NULL AND relation_id IS NOT NULL AND data_type = 'UUID')",
            name="ck_diagram_attributes_fk_invariants",
        ),
    )

    class_id: uuid.UUID = Field(
        foreign_key="diagram_classes.id",
        index=True,
        nullable=False,
        ondelete="CASCADE",
    )
    name: str = Field(
        sa_column=Column(String(255), nullable=False)
    )
    data_type: str | None = Field(
        default=None,
        sa_column=Column(String(50), nullable=True),
    )
    position: int = Field(
        sa_column=Column(Integer, nullable=False)
    )
    is_primary_key: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False)
    )
    is_nullable: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False)
    )
    is_foreign_key: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    referenced_class_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="diagram_classes.id",
        index=True,
        nullable=True,
        ondelete="CASCADE",
    )
    relation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="diagram_relations.id",
        index=True,
        nullable=True,
        ondelete="CASCADE",
    )

