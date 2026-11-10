import re
from typing import Any
from uuid import UUID

from app.modules.diagram.domain.exceptions import (
    InvalidDiagramRelationMaterializationException,
)
from app.modules.diagram.domain.services.diagram_relation_materialization_policy import (
    MaterializationPlan,
    MaterializationStrategy,
)


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
