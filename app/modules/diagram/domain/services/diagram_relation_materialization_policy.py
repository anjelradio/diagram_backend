from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType
from app.modules.diagram.domain.exceptions import (
    InvalidDiagramRelationMaterializationException,
)


class MaterializationStrategy(StrEnum):
    FOREIGN_KEY = "FOREIGN_KEY"
    SHARED_PRIMARY_KEY = "SHARED_PRIMARY_KEY"
    BRIDGE_CLASS = "BRIDGE_CLASS"


@dataclass(frozen=True, slots=True)
class ForeignKeyRule:
    receiving_class_id: UUID
    referenced_class_id: UUID
    is_nullable: bool


@dataclass(frozen=True, slots=True)
class SharedPrimaryKeyRule:
    subclass_id: UUID
    superclass_id: UUID


@dataclass(frozen=True, slots=True)
class BridgeClassRule:
    source_class_id: UUID
    target_class_id: UUID


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    strategy: MaterializationStrategy
    foreign_key: ForeignKeyRule | None = None
    shared_primary_key: SharedPrimaryKeyRule | None = None
    bridge_class: BridgeClassRule | None = None


def determine_materialization_plan(
    relation_type: DiagramRelationType,
    source_class_id: UUID,
    target_class_id: UUID,
    source_attributes_count: int = 1,
    target_attributes_count: int = 1,
    source_cardinality: DiagramCardinality | None = None,
    target_cardinality: DiagramCardinality | None = None,
) -> MaterializationPlan:
    """Regla de dominio pura para seleccionar estrategia, receptor y nulabilidad."""
    structural_rules = {
        DiagramRelationType.GENERALIZATION: (source_class_id, target_class_id, False),
        DiagramRelationType.AGGREGATION: (target_class_id, source_class_id, True),
        DiagramRelationType.COMPOSITION: (target_class_id, source_class_id, False),
        DiagramRelationType.REALIZATION: (source_class_id, target_class_id, False),
        DiagramRelationType.DEPENDENCY: (source_class_id, target_class_id, True),
    }
    if relation_type in structural_rules:
        receiver, reference, nullable = structural_rules[relation_type]
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(receiver, reference, nullable),
        )

    if relation_type != DiagramRelationType.ASSOCIATION:
        raise InvalidDiagramRelationMaterializationException()
    if source_cardinality is None or target_cardinality is None:
        raise InvalidDiagramRelationMaterializationException()

    many = {DiagramCardinality.ZERO_OR_MORE, DiagramCardinality.ONE_OR_MORE}
    source_many = source_cardinality in many
    target_many = target_cardinality in many
    if source_many and target_many:
        return MaterializationPlan(
            strategy=MaterializationStrategy.BRIDGE_CLASS,
            bridge_class=BridgeClassRule(source_class_id, target_class_id),
        )

    if source_class_id == target_class_id:
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(source_class_id, source_class_id, True),
        )

    if source_many:
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                source_class_id,
                target_class_id,
                target_cardinality == DiagramCardinality.ZERO_OR_ONE,
            ),
        )
    if target_many:
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                target_class_id,
                source_class_id,
                source_cardinality == DiagramCardinality.ZERO_OR_ONE,
            ),
        )

    # 1:1: receptora con más atributos; empates van al destino.
    if source_attributes_count > target_attributes_count:
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                source_class_id,
                target_class_id,
                target_cardinality == DiagramCardinality.ZERO_OR_ONE,
            ),
        )
    return MaterializationPlan(
        strategy=MaterializationStrategy.FOREIGN_KEY,
        foreign_key=ForeignKeyRule(
            target_class_id,
            source_class_id,
            source_cardinality == DiagramCardinality.ZERO_OR_ONE,
        ),
    )
