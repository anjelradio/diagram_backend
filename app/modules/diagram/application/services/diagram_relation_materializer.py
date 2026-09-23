import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.domain.exceptions import (
    InvalidDiagramRelationMaterializationException,
)


class MaterializationStrategy(StrEnum):
    FOREIGN_KEY = "FOREIGN_KEY"
    SHARED_PRIMARY_KEY = "SHARED_PRIMARY_KEY"
    BRIDGE_CLASS = "BRIDGE_CLASS"


@dataclass(frozen=True)
class ForeignKeyRule:
    receiving_class_id: UUID
    referenced_class_id: UUID
    is_nullable: bool


@dataclass(frozen=True)
class SharedPrimaryKeyRule:
    subclass_id: UUID
    superclass_id: UUID


@dataclass(frozen=True)
class BridgeClassRule:
    source_class_id: UUID
    target_class_id: UUID


@dataclass(frozen=True)
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
    """Calcula la estrategia determinista de materialización y los roles de extremos."""
    if relation_type == DiagramRelationType.GENERALIZATION:
        return MaterializationPlan(
            strategy=MaterializationStrategy.SHARED_PRIMARY_KEY,
            shared_primary_key=SharedPrimaryKeyRule(
                subclass_id=source_class_id,
                superclass_id=target_class_id,
            ),
        )

    if relation_type == DiagramRelationType.AGGREGATION:
        # Origen = Todo, Destino = Parte; FK en destino hacia origen, nullable
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                receiving_class_id=target_class_id,
                referenced_class_id=source_class_id,
                is_nullable=True,
            ),
        )

    if relation_type == DiagramRelationType.COMPOSITION:
        # Origen = Todo, Destino = Parte; FK en destino hacia origen, no nullable
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                receiving_class_id=target_class_id,
                referenced_class_id=source_class_id,
                is_nullable=False,
            ),
        )

    if relation_type == DiagramRelationType.REALIZATION:
        # Origen = Implementador, Destino = Contrato; FK en implementador hacia contrato, no nullable
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                receiving_class_id=source_class_id,
                referenced_class_id=target_class_id,
                is_nullable=False,
            ),
        )

    if relation_type == DiagramRelationType.DEPENDENCY:
        # Origen = Cliente, Destino = Proveedor; FK en cliente hacia proveedor, nullable
        return MaterializationPlan(
            strategy=MaterializationStrategy.FOREIGN_KEY,
            foreign_key=ForeignKeyRule(
                receiving_class_id=source_class_id,
                referenced_class_id=target_class_id,
                is_nullable=True,
            ),
        )

    if relation_type == DiagramRelationType.ASSOCIATION:
        if source_cardinality is None or target_cardinality is None:
            raise InvalidDiagramRelationMaterializationException()

        source_many = source_cardinality in (
            DiagramCardinality.ZERO_OR_MORE,
            DiagramCardinality.ONE_OR_MORE,
        )
        target_many = target_cardinality in (
            DiagramCardinality.ZERO_OR_MORE,
            DiagramCardinality.ONE_OR_MORE,
        )

        # Caso N:M (tanto normal como reflexivo)
        if source_many and target_many:
            return MaterializationPlan(
                strategy=MaterializationStrategy.BRIDGE_CLASS,
                bridge_class=BridgeClassRule(
                    source_class_id=source_class_id,
                    target_class_id=target_class_id,
                ),
            )

        # Caso Recursivo (Auto-asociación 1:1 o 1:N)
        if source_class_id == target_class_id:
            return MaterializationPlan(
                strategy=MaterializationStrategy.FOREIGN_KEY,
                foreign_key=ForeignKeyRule(
                    receiving_class_id=source_class_id,
                    referenced_class_id=source_class_id,
                    is_nullable=True,
                ),
            )

        # Caso 1:N (source es *, target es max 1)
        if source_many and not target_many:
            is_nullable = target_cardinality == DiagramCardinality.ZERO_OR_ONE
            return MaterializationPlan(
                strategy=MaterializationStrategy.FOREIGN_KEY,
                foreign_key=ForeignKeyRule(
                    receiving_class_id=source_class_id,
                    referenced_class_id=target_class_id,
                    is_nullable=is_nullable,
                ),
            )

        # Caso 1:N (target es *, source es max 1)
        if target_many and not source_many:
            is_nullable = source_cardinality == DiagramCardinality.ZERO_OR_ONE
            return MaterializationPlan(
                strategy=MaterializationStrategy.FOREIGN_KEY,
                foreign_key=ForeignKeyRule(
                    receiving_class_id=target_class_id,
                    referenced_class_id=source_class_id,
                    is_nullable=is_nullable,
                ),
            )

        # Caso 1:1 (ambos max 1)
        # Regla: FK en clase con más atributos; empate en destino
        if source_attributes_count > target_attributes_count:
            is_nullable = target_cardinality == DiagramCardinality.ZERO_OR_ONE
            return MaterializationPlan(
                strategy=MaterializationStrategy.FOREIGN_KEY,
                foreign_key=ForeignKeyRule(
                    receiving_class_id=source_class_id,
                    referenced_class_id=target_class_id,
                    is_nullable=is_nullable,
                ),
            )
        else:
            is_nullable = source_cardinality == DiagramCardinality.ZERO_OR_ONE
            return MaterializationPlan(
                strategy=MaterializationStrategy.FOREIGN_KEY,
                foreign_key=ForeignKeyRule(
                    receiving_class_id=target_class_id,
                    referenced_class_id=source_class_id,
                    is_nullable=is_nullable,
                ),
            )

    raise InvalidDiagramRelationMaterializationException()


def generate_bridge_class_name(
    source_name: str,
    target_name: str,
    existing_class_names: set[str] | list[str],
) -> str:
    """Genera el nombre PascalCase para la clase puente evitando colisiones en el proyecto."""
    clean_source = (
        "".join(
            part.capitalize()
            for part in re.split(r"[\s_-]+", source_name.strip())
            if part
        )
        or "Source"
    )
    clean_target = (
        "".join(
            part.capitalize()
            for part in re.split(r"[\s_-]+", target_name.strip())
            if part
        )
        or "Target"
    )
    base_name = f"{clean_source}{clean_target}"

    lower_existing = {name.lower() for name in existing_class_names}
    if base_name.lower() not in lower_existing:
        return base_name

    suffix = 2
    while f"{base_name.lower()}{suffix}" in lower_existing:
        suffix += 1
    return f"{base_name}{suffix}"


def calculate_bridge_class_position(
    source_x: float,
    source_y: float,
    target_x: float,
    target_y: float,
) -> tuple[float, float]:
    """Calcula la posición inicial de la clase puente: centro horizontal y +180px vertical."""
    center_x = (source_x + target_x) / 2.0
    center_y = (source_y + target_y) / 2.0 + 180.0
    return (center_x, center_y)


def validate_relation_materialization(
    relation_id: UUID,
    plan: MaterializationPlan,
    materialization_data: dict[str, Any],
) -> None:
    """Valida exhaustivamente que el payload enviado por el cliente concuerde con el plan determinista."""
    strategy = materialization_data.get("strategy")
    if strategy != plan.strategy.value:
        raise InvalidDiagramRelationMaterializationException()

    foreign_attrs = materialization_data.get("foreign_attributes") or []
    spk_data = materialization_data.get("shared_primary_key")
    bridge_data = materialization_data.get("bridge_class")

    if plan.strategy == MaterializationStrategy.FOREIGN_KEY:
        if spk_data is not None or bridge_data is not None:
            raise InvalidDiagramRelationMaterializationException()
        if len(foreign_attrs) != 1:
            raise InvalidDiagramRelationMaterializationException()

        fa = foreign_attrs[0]
        rule = plan.foreign_key
        assert rule is not None

        if UUID(str(fa["class_id"])) != rule.receiving_class_id:
            raise InvalidDiagramRelationMaterializationException()
        if UUID(str(fa["referenced_class_id"])) != rule.referenced_class_id:
            raise InvalidDiagramRelationMaterializationException()
        if UUID(str(fa["relation_id"])) != relation_id:
            raise InvalidDiagramRelationMaterializationException()
        if bool(fa["is_nullable"]) != rule.is_nullable:
            raise InvalidDiagramRelationMaterializationException()
        if not bool(fa["is_foreign_key"]) or bool(fa["is_primary_key"]):
            raise InvalidDiagramRelationMaterializationException()
        if fa.get("data_type") != "UUID":
            raise InvalidDiagramRelationMaterializationException()
        if int(fa.get("position", 0)) < 1:
            raise InvalidDiagramRelationMaterializationException()

    elif plan.strategy == MaterializationStrategy.SHARED_PRIMARY_KEY:
        if foreign_attrs or bridge_data is not None or spk_data is None:
            raise InvalidDiagramRelationMaterializationException()

        spk_rule = plan.shared_primary_key
        assert spk_rule is not None

        if UUID(str(spk_data["class_id"])) != spk_rule.subclass_id:
            raise InvalidDiagramRelationMaterializationException()
        if UUID(str(spk_data["referenced_class_id"])) != spk_rule.superclass_id:
            raise InvalidDiagramRelationMaterializationException()
        if UUID(str(spk_data["relation_id"])) != relation_id:
            raise InvalidDiagramRelationMaterializationException()

    elif plan.strategy == MaterializationStrategy.BRIDGE_CLASS:
        if foreign_attrs or spk_data is not None or bridge_data is None:
            raise InvalidDiagramRelationMaterializationException()

        bridge_rule = plan.bridge_class
        assert bridge_rule is not None

        bridge_id = UUID(str(bridge_data["id"]))
        primary_attr = bridge_data.get("primary_attribute")
        bridge_foreign_attrs = bridge_data.get("foreign_attributes") or []

        if not primary_attr or len(bridge_foreign_attrs) != 2:
            raise InvalidDiagramRelationMaterializationException()

        # Validar PK canónica de la clase puente
        if (
            primary_attr.get("name") != "id"
            or primary_attr.get("data_type") != "UUID"
            or int(primary_attr.get("position", -1)) != 0
            or not bool(primary_attr.get("is_primary_key"))
            or bool(primary_attr.get("is_nullable"))
        ):
            raise InvalidDiagramRelationMaterializationException()

        # Validar las dos FK de la clase puente
        referenced_ids = set()
        positions = set()
        fk_names = set()
        for fa in bridge_foreign_attrs:
            if UUID(str(fa["class_id"])) != bridge_id:
                raise InvalidDiagramRelationMaterializationException()
            if UUID(str(fa["relation_id"])) != relation_id:
                raise InvalidDiagramRelationMaterializationException()
            if not bool(fa["is_foreign_key"]) or bool(fa["is_primary_key"]):
                raise InvalidDiagramRelationMaterializationException()
            if bool(fa["is_nullable"]):
                raise InvalidDiagramRelationMaterializationException()
            if fa.get("data_type") != "UUID":
                raise InvalidDiagramRelationMaterializationException()

            ref_id = UUID(str(fa["referenced_class_id"]))
            referenced_ids.add(ref_id)
            positions.add(int(fa.get("position", 0)))
            fk_name = str(fa.get("name", "")).strip().lower()
            if not fk_name or fk_name in fk_names:
                raise InvalidDiagramRelationMaterializationException()
            fk_names.add(fk_name)

        expected_refs = {bridge_rule.source_class_id, bridge_rule.target_class_id}
        if referenced_ids != expected_refs:
            raise InvalidDiagramRelationMaterializationException()
        if len(positions) != 2 or any(pos < 1 for pos in positions):
            raise InvalidDiagramRelationMaterializationException()
