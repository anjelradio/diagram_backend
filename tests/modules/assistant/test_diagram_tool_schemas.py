"""Pruebas para el esquema y validación condicional de herramientas de mutación del diagrama."""

import pytest
from uuid import uuid4

from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
    validate_actions,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType


def _make_action(kind: str, **kwargs) -> dict:
    return {
        "operation_id": f"op-{uuid4().hex[:8]}",
        "kind": kind,
        **kwargs,
    }


def test_create_relation_complete_association_passes():
    src_id = str(uuid4())
    tgt_id = str(uuid4())
    payload = {
        "actions": [
            _make_action(
                "CREATE_RELATION",
                relation_type="ASSOCIATION",
                source_class_id=src_id,
                target_class_id=tgt_id,
                source_cardinality="1",
                target_cardinality="0..*",
                name="contiene",
            )
        ]
    }
    normalized = validate_actions(payload)
    assert len(normalized) == 1
    action = normalized[0]
    assert action["relation_type"] == "ASSOCIATION"
    assert action["source_cardinality"] == "1"
    assert action["target_cardinality"] == "0..*"
    assert action["name"] == "contiene"


def test_create_relation_association_missing_cardinalities_fails():
    src_id = str(uuid4())
    tgt_id = str(uuid4())

    # Missing target_cardinality
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="ASSOCIATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    source_cardinality="1",
                )
            ]
        })

    # target_cardinality is None
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="ASSOCIATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    source_cardinality="1",
                    target_cardinality=None,
                )
            ]
        })

    # Missing source_cardinality
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="ASSOCIATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    target_cardinality="0..*",
                )
            ]
        })

    # source_cardinality is None
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="ASSOCIATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    source_cardinality=None,
                    target_cardinality="0..*",
                )
            ]
        })


def test_create_relation_association_one_to_one_canonicalization():
    src_id = str(uuid4())
    tgt_id = str(uuid4())
    payload = {
        "actions": [
            _make_action(
                "CREATE_RELATION",
                relation_type="ASSOCIATION",
                source_class_id=src_id,
                target_class_id=tgt_id,
                source_cardinality="1..1",
                target_cardinality="1..1",
            )
        ]
    }
    normalized = validate_actions(payload)
    assert len(normalized) == 1
    action = normalized[0]
    assert action["source_cardinality"] == "1"
    assert action["target_cardinality"] == "1"


def test_create_relation_structural_null_cardinalities_passes():
    src_id = str(uuid4())
    tgt_id = str(uuid4())

    structural_types = [
        "AGGREGATION",
        "COMPOSITION",
        "GENERALIZATION",
        "REALIZATION",
        "DEPENDENCY",
    ]
    for st in structural_types:
        payload = {
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type=st,
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                )
            ]
        }
        normalized = validate_actions(payload)
        assert len(normalized) == 1
        assert normalized[0]["relation_type"] == st
        assert normalized[0].get("source_cardinality") is None
        assert normalized[0].get("target_cardinality") is None


def test_create_relation_structural_with_cardinality_forbidden():
    src_id = str(uuid4())
    tgt_id = str(uuid4())

    # Structural with source_cardinality
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="COMPOSITION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    source_cardinality="1",
                )
            ]
        })

    # Structural with target_cardinality
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="GENERALIZATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    target_cardinality="0..*",
                )
            ]
        })


def test_create_relation_mixed_forms_rejected():
    src_id = str(uuid4())
    tgt_id = str(uuid4())

    # Invalid cardinality value
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="ASSOCIATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                    source_cardinality="muchos",
                    target_cardinality="1",
                )
            ]
        })

    # Unknown relation type
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_RELATION",
                    relation_type="INVALID_RELATION",
                    source_class_id=src_id,
                    target_class_id=tgt_id,
                )
            ]
        })


def test_kind_relation_types_normalized_to_create_relation():
    src_id = str(uuid4())
    tgt_id = str(uuid4())

    # When LLM sends kind="ASSOCIATION" directly
    payload = {
        "actions": [
            {
                "operation_id": "op_assoc",
                "kind": "ASSOCIATION",
                "source_class_id": src_id,
                "target_class_id": tgt_id,
                "source_cardinality": "1",
                "target_cardinality": "0..*",
                "name": "realiza",
            },
            {
                "operation_id": "op_comp",
                "kind": "COMPOSITION",
                "source_class_id": src_id,
                "target_class_id": tgt_id,
                "head_class": "Padre",  # Harmless head_class should be stripped
            },
            {
                "operation_id": "op_prefixed",
                "kind": "CREATE_AGGREGATION",
                "source_class_id": src_id,
                "target_class_id": tgt_id,
            },
        ]
    }
    normalized = validate_actions(payload)
    assert len(normalized) == 3

    assert normalized[0]["kind"] == "CREATE_RELATION"
    assert normalized[0]["relation_type"] == "ASSOCIATION"
    assert normalized[0]["source_cardinality"] == "1"
    assert normalized[0]["target_cardinality"] == "0..*"
    assert normalized[0]["name"] == "realiza"

    assert normalized[1]["kind"] == "CREATE_RELATION"
    assert normalized[1]["relation_type"] == "COMPOSITION"
    assert "head_class" not in normalized[1]

    assert normalized[2]["kind"] == "CREATE_RELATION"
    assert normalized[2]["relation_type"] == "AGGREGATION"

