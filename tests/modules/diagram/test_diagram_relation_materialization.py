import uuid
import pytest

from app.modules.diagram.application.services.diagram_relation_materializer import (
    MaterializationStrategy,
    calculate_bridge_class_position,
    determine_materialization_plan,
    generate_bridge_class_name,
    validate_relation_materialization,
)
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType
from app.modules.diagram.domain.exceptions import (
    InvalidDiagramRelationMaterializationException,
)


def test_one_to_many_materialization():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # 1 a 0..* -> FK en target, referenciando source (1 no nullable)
    plan_1_to_n = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )
    assert plan_1_to_n.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_1_to_n.foreign_key.receiving_class_id == target_id
    assert plan_1_to_n.foreign_key.referenced_class_id == source_id
    assert not plan_1_to_n.foreign_key.is_nullable

    # 0..1 a 1..* -> FK en target, referenciando source (0..1 es nullable)
    plan_01_to_n = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.ZERO_OR_ONE,
        target_cardinality=DiagramCardinality.ONE_OR_MORE,
    )
    assert plan_01_to_n.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_01_to_n.foreign_key.receiving_class_id == target_id
    assert plan_01_to_n.foreign_key.referenced_class_id == source_id
    assert plan_01_to_n.foreign_key.is_nullable

    # 0..* a 1 -> FK en source, referenciando target (1 no nullable)
    plan_n_to_1 = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.ZERO_OR_MORE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )
    assert plan_n_to_1.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_n_to_1.foreign_key.receiving_class_id == source_id
    assert plan_n_to_1.foreign_key.referenced_class_id == target_id
    assert not plan_n_to_1.foreign_key.is_nullable


def test_one_to_one_materialization_by_attributes_count():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Source tiene más atributos (3 vs 1) -> FK en source
    plan_source_wins = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_attributes_count=3,
        target_attributes_count=1,
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )
    assert plan_source_wins.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_source_wins.foreign_key.receiving_class_id == source_id
    assert plan_source_wins.foreign_key.referenced_class_id == target_id
    assert not plan_source_wins.foreign_key.is_nullable

    # Target tiene más atributos (1 vs 3) -> FK en target
    plan_target_wins = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_attributes_count=1,
        target_attributes_count=3,
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )
    assert plan_target_wins.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_target_wins.foreign_key.receiving_class_id == target_id
    assert plan_target_wins.foreign_key.referenced_class_id == source_id

    # Empate de atributos (2 vs 2) -> FK en destino (target)
    plan_tie = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_attributes_count=2,
        target_attributes_count=2,
        source_cardinality=DiagramCardinality.ZERO_OR_ONE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )
    assert plan_tie.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_tie.foreign_key.receiving_class_id == target_id
    assert plan_tie.foreign_key.referenced_class_id == source_id
    # Como source era 0..1, la FK en target es nullable
    assert plan_tie.foreign_key.is_nullable


def test_aggregation_and_composition_materialization():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Agregación: Todo (source) -> Parte (target); FK en target, nullable
    agg_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.AGGREGATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    assert agg_plan.strategy == MaterializationStrategy.FOREIGN_KEY
    assert agg_plan.foreign_key.receiving_class_id == target_id
    assert agg_plan.foreign_key.referenced_class_id == source_id
    assert agg_plan.foreign_key.is_nullable

    # Composición: Todo (source) -> Parte (target); FK en target, no nullable
    comp_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.COMPOSITION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    assert comp_plan.strategy == MaterializationStrategy.FOREIGN_KEY
    assert comp_plan.foreign_key.receiving_class_id == target_id
    assert comp_plan.foreign_key.referenced_class_id == source_id
    assert not comp_plan.foreign_key.is_nullable


def test_generalization_shared_primary_key():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    gen_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.GENERALIZATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    assert gen_plan.strategy == MaterializationStrategy.SHARED_PRIMARY_KEY
    assert gen_plan.shared_primary_key.subclass_id == source_id
    assert gen_plan.shared_primary_key.superclass_id == target_id


def test_realization_and_dependency_materialization():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Realización: Implementador (source) -> Contrato (target); FK en implementador, no nullable
    real_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.REALIZATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    assert real_plan.strategy == MaterializationStrategy.FOREIGN_KEY
    assert real_plan.foreign_key.receiving_class_id == source_id
    assert real_plan.foreign_key.referenced_class_id == target_id
    assert not real_plan.foreign_key.is_nullable

    # Dependencia: Cliente (source) -> Proveedor (target); FK en cliente, nullable
    dep_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.DEPENDENCY,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    assert dep_plan.strategy == MaterializationStrategy.FOREIGN_KEY
    assert dep_plan.foreign_key.receiving_class_id == source_id
    assert dep_plan.foreign_key.referenced_class_id == target_id
    assert dep_plan.foreign_key.is_nullable


def test_many_to_many_materialization():
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    nm_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.ZERO_OR_MORE,
        target_cardinality=DiagramCardinality.ONE_OR_MORE,
    )
    assert nm_plan.strategy == MaterializationStrategy.BRIDGE_CLASS
    assert nm_plan.bridge_class.source_class_id == source_id
    assert nm_plan.bridge_class.target_class_id == target_id


def test_generate_bridge_class_name():
    # Sin colisión
    name1 = generate_bridge_class_name("Estudiante", "Curso", set())
    assert name1 == "EstudianteCurso"

    # Con colisión simple
    name2 = generate_bridge_class_name("Estudiante", "Curso", {"estudiantecurso"})
    assert name2 == "EstudianteCurso2"

    # Con colisión múltiple
    name3 = generate_bridge_class_name(
        "Estudiante",
        "Curso",
        {"estudiantecurso", "estudiantecurso2", "estudiantecurso3"},
    )
    assert name3 == "EstudianteCurso4"


def test_calculate_bridge_class_position():
    pos = calculate_bridge_class_position(100.0, 200.0, 300.0, 400.0)
    assert pos == (200.0, 480.0)  # midpoint (200, 300) + 180 = (200, 480)


def test_validate_relation_materialization_foreign_key():
    relation_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    plan = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )

    valid_payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(target_id),
                "name": "source_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": False,
                "is_foreign_key": True,
                "referenced_class_id": str(source_id),
                "relation_id": str(relation_id),
            }
        ],
        "shared_primary_key": None,
        "bridge_class": None,
    }

    # Debe validar sin excepción
    validate_relation_materialization(relation_id, plan, valid_payload)

    # Debe fallar si la estrategia no coincide
    invalid_strategy = {**valid_payload, "strategy": "SHARED_PRIMARY_KEY"}
    with pytest.raises(InvalidDiagramRelationMaterializationException):
        validate_relation_materialization(relation_id, plan, invalid_strategy)

    # Debe fallar si el class_id que recibe la FK es incorrecto
    invalid_class = {
        **valid_payload,
        "foreign_attributes": [
            {**valid_payload["foreign_attributes"][0], "class_id": str(source_id)}
        ],
    }
    with pytest.raises(InvalidDiagramRelationMaterializationException):
        validate_relation_materialization(relation_id, plan, invalid_class)


def test_parity_matrix_for_all_relation_types():
    """Valida la matriz de paridad completa para las 8 variantes de materialización."""
    relation_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # 1. Agregación: Todo (source) -> Parte (target); FK en target, nullable=True
    agg_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.AGGREGATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    agg_payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(target_id),
                "name": "todo_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": True,
                "is_foreign_key": True,
                "referenced_class_id": str(source_id),
                "relation_id": str(relation_id),
            }
        ],
        "shared_primary_key": None,
        "bridge_class": None,
    }
    validate_relation_materialization(relation_id, agg_plan, agg_payload)

    # 2. Composición: Todo (source) -> Parte (target); FK en target, is_nullable=False
    comp_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.COMPOSITION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    comp_payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(target_id),
                "name": "todo_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": False,
                "is_foreign_key": True,
                "referenced_class_id": str(source_id),
                "relation_id": str(relation_id),
            }
        ],
        "shared_primary_key": None,
        "bridge_class": None,
    }
    validate_relation_materialization(relation_id, comp_plan, comp_payload)

    # 3. Generalización: Subclase (source) -> Superclase (target); SHARED_PRIMARY_KEY en subclass
    gen_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.GENERALIZATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    gen_payload = {
        "strategy": "SHARED_PRIMARY_KEY",
        "foreign_attributes": [],
        "shared_primary_key": {
            "attribute_id": str(uuid.uuid4()),
            "class_id": str(source_id),
            "referenced_class_id": str(target_id),
            "relation_id": str(relation_id),
        },
        "bridge_class": None,
    }
    validate_relation_materialization(relation_id, gen_plan, gen_payload)

    # 4. Realización: Implementador (source) -> Contrato (target); FK en implementador, is_nullable=False
    real_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.REALIZATION,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    real_payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(source_id),
                "name": "contrato_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": False,
                "is_foreign_key": True,
                "referenced_class_id": str(target_id),
                "relation_id": str(relation_id),
            }
        ],
        "shared_primary_key": None,
        "bridge_class": None,
    }
    validate_relation_materialization(relation_id, real_plan, real_payload)

    # 5. Dependencia: Cliente (source) -> Proveedor (target); FK en cliente, is_nullable=True
    dep_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.DEPENDENCY,
        source_class_id=source_id,
        target_class_id=target_id,
    )
    dep_payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(source_id),
                "name": "proveedor_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": True,
                "is_foreign_key": True,
                "referenced_class_id": str(target_id),
                "relation_id": str(relation_id),
            }
        ],
        "shared_primary_key": None,
        "bridge_class": None,
    }
    validate_relation_materialization(relation_id, dep_plan, dep_payload)

    # 6. Asociación N:M: BRIDGE_CLASS con su PK y 2 FKs
    nm_plan = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=source_id,
        target_class_id=target_id,
        source_cardinality=DiagramCardinality.ZERO_OR_MORE,
        target_cardinality=DiagramCardinality.ONE_OR_MORE,
    )
    bridge_id = uuid.uuid4()
    nm_payload = {
        "strategy": "BRIDGE_CLASS",
        "foreign_attributes": [],
        "shared_primary_key": None,
        "bridge_class": {
            "id": str(bridge_id),
            "name": "SourceTarget",
            "position_x": 100.0,
            "position_y": 200.0,
            "handle": "TOP_CENTER",
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
            "foreign_attributes": [
                {
                    "id": str(uuid.uuid4()),
                    "class_id": str(bridge_id),
                    "name": "source_id",
                    "data_type": "UUID",
                    "position": 1,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(source_id),
                    "relation_id": str(relation_id),
                },
                {
                    "id": str(uuid.uuid4()),
                    "class_id": str(bridge_id),
                    "name": "target_id",
                    "data_type": "UUID",
                    "position": 2,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(target_id),
                    "relation_id": str(relation_id),
                },
            ],
        },
    }
    validate_relation_materialization(relation_id, nm_plan, nm_payload)


def test_self_referencing_one_to_many_and_one_to_one_materialization():
    class_id = uuid.uuid4()
    relation_id = uuid.uuid4()

    # Auto-asociación 1:N
    plan_self_1n = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=class_id,
        target_class_id=class_id,
        source_cardinality=DiagramCardinality.ZERO_OR_ONE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )
    assert plan_self_1n.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_self_1n.foreign_key.receiving_class_id == class_id
    assert plan_self_1n.foreign_key.referenced_class_id == class_id
    assert plan_self_1n.foreign_key.is_nullable is True

    # Auto-asociación 1:1
    plan_self_11 = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=class_id,
        target_class_id=class_id,
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )
    assert plan_self_11.strategy == MaterializationStrategy.FOREIGN_KEY
    assert plan_self_11.foreign_key.receiving_class_id == class_id
    assert plan_self_11.foreign_key.referenced_class_id == class_id
    assert plan_self_11.foreign_key.is_nullable is True

    # Validar payload de FK auto-referenciada
    payload = {
        "strategy": "FOREIGN_KEY",
        "foreign_attributes": [
            {
                "id": str(uuid.uuid4()),
                "class_id": str(class_id),
                "name": "parent_category_id",
                "data_type": "UUID",
                "position": 1,
                "is_primary_key": False,
                "is_nullable": True,
                "is_foreign_key": True,
                "referenced_class_id": str(class_id),
                "relation_id": str(relation_id),
            }
        ],
    }
    validate_relation_materialization(relation_id, plan_self_1n, payload)


def test_self_referencing_many_to_many_materialization():
    class_id = uuid.uuid4()
    relation_id = uuid.uuid4()
    bridge_id = uuid.uuid4()

    plan = determine_materialization_plan(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_class_id=class_id,
        target_class_id=class_id,
        source_cardinality=DiagramCardinality.ZERO_OR_MORE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )
    assert plan.strategy == MaterializationStrategy.BRIDGE_CLASS
    assert plan.bridge_class.source_class_id == class_id
    assert plan.bridge_class.target_class_id == class_id

    # Validar payload de puente reflexivo con dos FKs apuntando a la misma clase
    bridge_payload = {
        "strategy": "BRIDGE_CLASS",
        "bridge_class": {
            "id": str(bridge_id),
            "name": "PersonRelation",
            "position_x": 100.0,
            "position_y": 200.0,
            "handle": "TOP_CENTER",
            "primary_attribute": {
                "id": str(uuid.uuid4()),
                "name": "id",
                "data_type": "UUID",
                "position": 0,
                "is_primary_key": True,
                "is_nullable": False,
            },
            "foreign_attributes": [
                {
                    "id": str(uuid.uuid4()),
                    "class_id": str(bridge_id),
                    "name": "person_id",
                    "data_type": "UUID",
                    "position": 1,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(class_id),
                    "relation_id": str(relation_id),
                },
                {
                    "id": str(uuid.uuid4()),
                    "class_id": str(bridge_id),
                    "name": "related_person_id",
                    "data_type": "UUID",
                    "position": 2,
                    "is_primary_key": False,
                    "is_nullable": False,
                    "is_foreign_key": True,
                    "referenced_class_id": str(class_id),
                    "relation_id": str(relation_id),
                },
            ],
        },
    }
    validate_relation_materialization(relation_id, plan, bridge_payload)

