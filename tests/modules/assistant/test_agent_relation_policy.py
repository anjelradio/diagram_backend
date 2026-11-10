"""Pruebas unitarias para la política canónica de relaciones del asistente."""

import pytest
from uuid import uuid4

from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType
from tests.modules.assistant.fixtures.relation_cases import (
    ASSOCIATION_CARDINALITY_PAIRS,
    ASSOCIATION_EQUIVALENCE_CASES,
    EXPLICIT_HEAD_CASES,
    RELATION_SEMANTIC_ROLE_CASES,
    STRUCTURAL_PHRASE_CASES,
)


def test_cardinality_normalization_and_aliases():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        normalize_cardinality,
        is_valid_cardinality,
    )

    assert normalize_cardinality("1..1") == "1"
    assert normalize_cardinality("1") == "1"
    assert normalize_cardinality("0..1") == "0..1"
    assert normalize_cardinality("0..*") == "0..*"
    assert normalize_cardinality("1..*") == "1..*"
    assert normalize_cardinality(None) is None

    assert is_valid_cardinality("1..1") is True
    assert is_valid_cardinality("1") is True
    assert is_valid_cardinality("invalid") is False
    assert is_valid_cardinality(None) is False

    with pytest.raises(ValueError):
        normalize_cardinality("invalid_card")


def test_relation_family_classification():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        is_association,
        is_structural,
    )

    assert is_association(DiagramRelationType.ASSOCIATION) is True
    assert is_association("ASSOCIATION") is True
    assert is_association(DiagramRelationType.COMPOSITION) is False

    structural_types = [
        DiagramRelationType.AGGREGATION,
        DiagramRelationType.COMPOSITION,
        DiagramRelationType.GENERALIZATION,
        DiagramRelationType.REALIZATION,
        DiagramRelationType.DEPENDENCY,
    ]
    for st in structural_types:
        assert is_structural(st) is True
        assert is_structural(st.value) is True
    assert is_structural(DiagramRelationType.ASSOCIATION) is False


def test_validate_relation_request_issue_codes():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        RelationValidationIssueCode,
        validate_relation_request,
    )

    # 1. Asociación completa válida -> None
    assert (
        validate_relation_request(
            relation_type="ASSOCIATION",
            source_cardinality="1",
            target_cardinality="0..*",
        )
        is None
    )

    # Asociación con alias 1..1 -> válida (se normaliza)
    assert (
        validate_relation_request(
            relation_type="ASSOCIATION",
            source_cardinality="1..1",
            target_cardinality="1",
        )
        is None
    )

    # 2. Asociación con cardinalidad faltante -> relation_cardinality_required
    assert (
        validate_relation_request(
            relation_type="ASSOCIATION",
            source_cardinality="1",
            target_cardinality=None,
        )
        == RelationValidationIssueCode.RELATION_CARDINALITY_REQUIRED
    )
    assert (
        validate_relation_request(
            relation_type="ASSOCIATION",
            source_cardinality=None,
            target_cardinality="0..*",
        )
        == RelationValidationIssueCode.RELATION_CARDINALITY_REQUIRED
    )

    # 3. Relación estructural sin cardinalidad -> válida
    assert (
        validate_relation_request(
            relation_type="COMPOSITION",
            source_cardinality=None,
            target_cardinality=None,
        )
        is None
    )

    # 4. Relación estructural con cardinalidad prohibida -> relation_cardinality_forbidden
    assert (
        validate_relation_request(
            relation_type="COMPOSITION",
            source_cardinality="1",
            target_cardinality=None,
        )
        == RelationValidationIssueCode.RELATION_CARDINALITY_FORBIDDEN
    )
    assert (
        validate_relation_request(
            relation_type="GENERALIZATION",
            source_cardinality=None,
            target_cardinality="1..*",
        )
        == RelationValidationIssueCode.RELATION_CARDINALITY_FORBIDDEN
    )

    # 5. Cardinalidad no reconocida -> relation_combination_invalid
    assert (
        validate_relation_request(
            relation_type="ASSOCIATION",
            source_cardinality="muchos",
            target_cardinality="1",
        )
        == RelationValidationIssueCode.RELATION_COMBINATION_INVALID
    )


def test_structural_role_metadata_and_head_placement():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        get_head_placement,
        get_semantic_roles,
    )

    for rel_type, case in RELATION_SEMANTIC_ROLE_CASES.items():
        assert get_head_placement(rel_type) == case.head_endpoint
        src_role, tgt_role = get_semantic_roles(rel_type)
        assert src_role == case.source_role
        assert tgt_role == case.target_role


def test_translate_head_to_endpoints():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        translate_head_to_endpoints,
        RelationValidationIssueCode,
    )

    for case in EXPLICIT_HEAD_CASES:
        src, tgt = translate_head_to_endpoints(
            relation_type=case.relation_type,
            endpoint_a=case.head_class,
            endpoint_b=case.other_class,
            head_class=case.head_class,
        )
        assert src == case.expected_source_class
        assert tgt == case.expected_target_class

        # Invertir el orden de los endpoints pasados debe dar el mismo resultado canónico
        src2, tgt2 = translate_head_to_endpoints(
            relation_type=case.relation_type,
            endpoint_a=case.other_class,
            endpoint_b=case.head_class,
            head_class=case.head_class,
        )
        assert src2 == case.expected_source_class
        assert tgt2 == case.expected_target_class

    # Head que no coincide con ninguno de los dos extremos
    with pytest.raises(ValueError) as exc:
        translate_head_to_endpoints(
            relation_type=DiagramRelationType.COMPOSITION,
            endpoint_a="Casa",
            endpoint_b="Habitación",
            head_class="OtraClase",
        )
    assert str(exc.value) == RelationValidationIssueCode.RELATION_DIRECTION_REQUIRED

    # Asociación con head_class no es válida
    with pytest.raises(ValueError) as exc:
        translate_head_to_endpoints(
            relation_type=DiagramRelationType.ASSOCIATION,
            endpoint_a="Pedido",
            endpoint_b="Producto",
            head_class="Pedido",
        )
    assert str(exc.value) == RelationValidationIssueCode.RELATION_COMBINATION_INVALID


def test_association_and_structural_equivalence():
    from app.modules.assistant.application.services.diagram.agent_relation_policy import (
        are_relations_equivalent,
    )

    for case in ASSOCIATION_EQUIVALENCE_CASES:
        res = are_relations_equivalent(
            type1=DiagramRelationType.ASSOCIATION,
            source1=case.source_class,
            target1=case.target_class,
            source_card1=case.source_cardinality,
            target_card1=case.target_cardinality,
            name1=case.name,
            type2=DiagramRelationType.ASSOCIATION,
            source2=case.candidate_source_class,
            target2=case.candidate_target_class,
            source_card2=case.candidate_source_cardinality,
            target_card2=case.candidate_target_cardinality,
            name2=case.candidate_name,
        )
        assert res is case.is_equivalent

    # Relaciones estructurales conservan dirección estricta
    assert (
        are_relations_equivalent(
            type1=DiagramRelationType.COMPOSITION,
            source1="Casa",
            target1="Habitación",
            source_card1=None,
            target_card1=None,
            name1="",
            type2=DiagramRelationType.COMPOSITION,
            source2="Casa",
            target2="Habitación",
            source_card2=None,
            target_card2=None,
            name2="",
        )
        is True
    )

    # Invertida en estructural NO es equivalente
    assert (
        are_relations_equivalent(
            type1=DiagramRelationType.COMPOSITION,
            source1="Casa",
            target1="Habitación",
            source_card1=None,
            target_card1=None,
            name1="",
            type2=DiagramRelationType.COMPOSITION,
            source2="Habitación",
            target2="Casa",
            source_card2=None,
            target_card2=None,
            name2="",
        )
        is False
    )

    # Distinto tipo nunca es equivalente
    assert (
        are_relations_equivalent(
            type1=DiagramRelationType.COMPOSITION,
            source1="Casa",
            target1="Habitación",
            source_card1=None,
            target_card1=None,
            name1="",
            type2=DiagramRelationType.AGGREGATION,
            source2="Casa",
            target2="Habitación",
            source_card2=None,
            target_card2=None,
            name2="",
        )
        is False
    )
