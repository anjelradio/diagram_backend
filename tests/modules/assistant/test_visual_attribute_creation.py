import pytest

from app.modules.assistant.application.services.diagram.diagram_tool_schemas import validate_actions
from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException


def test_visual_attribute_type_inference_nullable_default_and_unknown_type():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importa los atributos de Producto",
        scope={"classes": "all", "attributes": "all", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "nombre", "data_type": None, "key_kind": "ordinary"},
                    {"name": "atributo_desconocido", "data_type": None, "key_kind": "ordinary"},
                    {"name": "precio", "data_type": "DECIMAL", "nullable": False},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)
    attributes = normalized["classes"][0]["attributes"]
    assert [(item["name"], item["data_type"], item["nullable"]) for item in attributes] == [
        ("nombre", "TEXT", True),
        ("atributo_desconocido", None, True),
        ("precio", "DECIMAL", False),
    ]


def test_agent_create_attribute_schema_accepts_null_type_and_defaults_nullable():
    actions = validate_actions(
        {
            "actions": [
                {
                    "operation_id": "name-attribute",
                    "kind": "CREATE_ATTRIBUTE",
                    "class_id": "00000000-0000-0000-0000-000000000001",
                    "name": "nombre",
                    "data_type": None,
                }
            ]
        }
    )

    assert actions[0]["data_type"] is None
    assert "nullable" not in actions[0]  # DiagramAttributeTools applies nullable=true.


def test_agent_create_attribute_schema_rejects_explicit_unsupported_type():
    with pytest.raises(AgentToolArgumentsException):
        validate_actions(
            {
                "actions": [
                    {
                        "operation_id": "bad-type",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": "00000000-0000-0000-0000-000000000001",
                        "name": "nombre",
                        "data_type": "VARCHAR",
                    }
                ]
            }
        )


def test_agent_tool_schema_rejects_manual_pk_and_fk_parameters():
    """US2: El esquema de herramientas rechaza propiedades para forzar PK o FK manuales."""
    # Rechazar is_primary_key en CREATE_ATTRIBUTE
    with pytest.raises(AgentToolArgumentsException):
        validate_actions(
            {
                "actions": [
                    {
                        "operation_id": "manual-pk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": "00000000-0000-0000-0000-000000000001",
                        "name": "id",
                        "is_primary_key": True,
                    }
                ]
            }
        )

    # Rechazar is_foreign_key o referenced_class_id en CREATE_ATTRIBUTE
    with pytest.raises(AgentToolArgumentsException):
        validate_actions(
            {
                "actions": [
                    {
                        "operation_id": "manual-fk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": "00000000-0000-0000-0000-000000000001",
                        "name": "cliente_id",
                        "is_foreign_key": True,
                        "referenced_class_id": "00000000-0000-0000-0000-000000000002",
                    }
                ]
            }
        )

