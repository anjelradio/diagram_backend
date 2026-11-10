"""Pruebas para las reglas de ignorado e intercepción de Llaves Primarias (PK) y Foráneas (FK)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.modules.assistant.domain.dialog.key_attribute_rules import (
    is_primary_key_name,
    is_foreign_key_name,
    is_any_key_name,
    extract_referenced_entity_from_fk,
    filter_secondary_attributes,
)
from app.modules.assistant.domain.dialog.semantic_validators import (
    validate_not_isolated_key_attribute,
)
from app.modules.assistant.application.services.dialog.turn_signals import (
    extract_turn_signals,
    is_isolated_fk_request,
    is_isolated_pk_request,
)
from app.modules.assistant.application.services.dialog.turn_interpreter import (
    TurnInterpreter,
)
from app.modules.assistant.application.services.dialog.dialog_policy import (
    DialogPolicy,
)
from app.modules.assistant.domain.dialog.dialog_frame import DialogState
from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)


def test_is_primary_key_name_detection():
    # Exactos
    assert is_primary_key_name("id") is True
    assert is_primary_key_name("ID") is True
    assert is_primary_key_name("uuid") is True
    assert is_primary_key_name("pk") is True
    assert is_primary_key_name("guid") is True

    # Coincidencia con nombre de clase
    assert is_primary_key_name("producto_id", class_name="Producto") is True
    assert is_primary_key_name("id_producto", class_name="Producto") is True
    assert is_primary_key_name("pk_producto", class_name="Producto") is True

    # No son PK
    assert is_primary_key_name("nombre", class_name="Producto") is False
    assert is_primary_key_name("precio", class_name="Producto") is False
    assert is_primary_key_name("categoria_id", class_name="Producto") is False
    assert is_primary_key_name("id_categoria", class_name="Producto") is False


def test_is_foreign_key_name_detection():
    # En clase Producto, atributos referenciando otras entidades
    assert is_foreign_key_name("categoria_id", class_name="Producto") is True
    assert is_foreign_key_name("id_categoria", class_name="Producto") is True
    assert is_foreign_key_name("usuario_id", class_name="Producto") is True
    assert is_foreign_key_name("fk_proveedor", class_name="Producto") is True
    assert is_foreign_key_name("cliente_fk", class_name="Producto") is True

    # Su propia PK no es FK
    assert is_foreign_key_name("id", class_name="Producto") is False
    assert is_foreign_key_name("producto_id", class_name="Producto") is False
    assert is_foreign_key_name("id_producto", class_name="Producto") is False

    # Atributos ordinarios
    assert is_foreign_key_name("nombre", class_name="Producto") is False
    assert is_foreign_key_name("precio", class_name="Producto") is False
    assert is_foreign_key_name("codigo_postal", class_name="Producto") is False
    assert is_foreign_key_name("activo", class_name="Producto") is False


def test_extract_referenced_entity_from_fk():
    assert extract_referenced_entity_from_fk("categoria_id") == "categoria"
    assert extract_referenced_entity_from_fk("id_categoria") == "categoria"
    assert extract_referenced_entity_from_fk("fk_usuario") == "usuario"
    assert extract_referenced_entity_from_fk("cliente_fk") == "cliente"
    assert extract_referenced_entity_from_fk("nombre") is None


def test_filter_secondary_attributes():
    attributes = [
        {"name": "id", "data_type": "UUID"},
        {"name": "nombre", "data_type": "TEXT"},
        {"name": "precio", "data_type": "DECIMAL"},
        {"name": "categoria_id", "data_type": "INTEGER"},
        {"name": "id_proveedor", "data_type": "INTEGER"},
        {"name": "stock", "data_type": "INTEGER"},
    ]
    valid, ignored = filter_secondary_attributes(attributes, class_name="Producto")

    valid_names = [a["name"] for a in valid]
    ignored_names = [a["name"] for a in ignored]

    assert valid_names == ["nombre", "precio", "stock"]
    assert ignored_names == ["id", "categoria_id", "id_proveedor"]


def test_semantic_validator_rejects_isolated_key_attributes():
    # PK
    valid_pk, err_pk = validate_not_isolated_key_attribute(attribute_name="id", class_name="Producto")
    assert valid_pk is False
    assert "No es necesario crear la clave primaria" in err_pk

    # FK
    valid_fk, err_fk = validate_not_isolated_key_attribute(attribute_name="categoria_id", class_name="Producto")
    assert valid_fk is False
    assert "Las claves foráneas no se crean como atributos manuales" in err_fk
    assert "Categoria" in err_fk

    # Atributo ordinario
    valid_ord, err_ord = validate_not_isolated_key_attribute(attribute_name="nombre", class_name="Producto")
    assert valid_ord is True
    assert err_ord is None


def test_turn_signals_isolated_fk_and_pk_intent():
    # Petición aislada de FK
    sig_fk1 = extract_turn_signals("Crea una llave foránea en la clase Producto")
    assert sig_fk1.is_fk_request is True
    assert sig_fk1.target_class_hint == "Producto"
    assert sig_fk1.related_class_hint is None

    # Petición aislada de FK con clase relacionada
    sig_fk2 = extract_turn_signals("Crea una llave foránea en Producto para relacionar con Categoría")
    assert sig_fk2.is_fk_request is True
    assert sig_fk2.target_class_hint == "Producto"
    assert sig_fk2.related_class_hint == "Categoría"

    # Petición aislada de PK
    sig_pk = extract_turn_signals("Crea una llave primaria en Producto")
    assert sig_pk.is_pk_request is True
    assert sig_pk.target_class_hint == "Producto"

    # Creación de clase normal no es petición aislada de FK ni PK
    sig_normal = extract_turn_signals("Crea una clase Producto con id, nombre y precio")
    assert sig_normal.is_fk_request is False
    assert sig_normal.is_pk_request is False


@pytest.mark.anyio
async def test_turn_interpreter_and_policy_fk_guidance():
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # 1. El usuario pide una llave foránea en Producto
    turn = await interpreter.interpret(
        user_message="Crea una llave foránea en la clase Producto",
        dialog_state=state,
    )
    assert turn.user_act == "request_foreign_key_guidance"
    assert turn.slots.get("relation.source_class") == "Producto"

    # 2. La política responde pedagógicamente
    decision = policy.decide(turn=turn, state=state)
    assert decision.assistant_act == "elicit_slots"
    assert "Las llaves foráneas no se crean como atributos manuales" in decision.assistant_message
    assert "¿Con qué otra clase deseas relacionar **Producto**" in decision.assistant_message


@pytest.mark.anyio
async def test_turn_interpreter_and_policy_pk_guidance():
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # 1. El usuario pide una llave primaria en Producto
    turn = await interpreter.interpret(
        user_message="Crea una llave primaria en Producto",
        dialog_state=state,
    )
    assert turn.user_act == "request_primary_key_guidance"
    assert turn.slots.get("class.name") == "Producto"

    # 2. La política responde explicando que Producto ya tiene id
    decision = policy.decide(turn=turn, state=state)
    assert decision.assistant_act == "disambiguate"
    assert "ya cuenta automáticamente con su llave primaria (`id`)" in decision.assistant_message


def test_visual_normalizer_ignores_pk_and_fk_attributes_even_if_reported_ordinary():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Copia la clase Producto tal cual",
        scope={"classes": "all", "attributes": "all", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "ordinary"},
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "precio", "data_type": "DECIMAL", "key_kind": "ordinary"},
                    {"name": "categoria_id", "data_type": "INTEGER", "key_kind": "ordinary"},
                    {"name": "id_proveedor", "data_type": "INTEGER", "key_kind": "ordinary"},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)
    norm_class = normalized["classes"][0]
    final_attr_names = [a["name"] for a in norm_class["attributes"]]

    # Solo deben quedar nombre y precio
    assert final_attr_names == ["nombre", "precio"]

    # id, categoria_id e id_proveedor deben figurar como derivados/ignorados
    derived = normalized["derived_attributes"]
    derived_tuples = [(d["attribute"], d["reason"]) for d in derived]
    assert ("id", "primary_key_created_with_class") in derived_tuples
    assert ("categoria_id", "foreign_key_created_with_relation") in derived_tuples
    assert ("id_proveedor", "foreign_key_created_with_relation") in derived_tuples
