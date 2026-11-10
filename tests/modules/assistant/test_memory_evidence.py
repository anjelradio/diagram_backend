"""Pruebas para la proyección de evidencia de memoria desde operation_ledger."""

from __future__ import annotations

import pytest

from app.modules.assistant.application.services.memory_evidence import (
    ConfirmedOperation,
    extract_confirmed_operations,
    format_confirmed_operations_text,
)


def test_extract_confirmed_operations_from_mixed_ledger():
    """Solo las operaciones con status='applied' son extraídas; 'rejected', 'failed', 'proposed', 'uncertain' son ignoradas."""
    mixed_ledger = [
        {
            "operation_id": "op-1",
            "action_kind": "CREATE_CLASS",
            "status": "applied",
            "entity_refs": [{"type": "class", "name": "Factura", "id": "11111111-1111-1111-1111-111111111111"}],
        },
        {
            "operation_id": "op-2",
            "action_kind": "CREATE_ATTRIBUTE",
            "status": "rejected",
            "entity_refs": [{"type": "attribute", "name": "total", "id": "22222222-2222-2222-2222-222222222222"}],
        },
        {
            "operation_id": "op-3",
            "action_kind": "CREATE_CLASS",
            "status": "failed",
            "entity_refs": [{"type": "class", "name": "Cliente"}],
        },
        {
            "operation_id": "op-4",
            "action_kind": "RENAME_CLASS",
            "status": "proposed",
            "entity_refs": [{"type": "class", "name": "Proveedor"}],
        },
        {
            "operation_id": "op-5",
            "action_kind": "DELETE_CLASS",
            "status": "uncertain",
            "entity_refs": [{"type": "class", "name": "Borrador"}],
        },
        {
            "operation_id": "op-6",
            "action_kind": "CREATE_ATTRIBUTE",
            "status": "applied",
            "entity_refs": [{"type": "attribute", "name": "subtotal", "id": "33333333-3333-3333-3333-333333333333"}],
        },
    ]

    confirmed = extract_confirmed_operations(mixed_ledger)

    assert len(confirmed) == 2
    assert confirmed[0].operation_id == "op-1"
    assert confirmed[0].action_kind == "CREATE_CLASS"
    assert "Factura" in confirmed[0].summary
    assert confirmed[1].operation_id == "op-6"
    assert confirmed[1].action_kind == "CREATE_ATTRIBUTE"
    assert "subtotal" in confirmed[1].summary

    # Ninguna operación no aplicada aparece
    extracted_ids = [op.operation_id for op in confirmed]
    assert "op-2" not in extracted_ids
    assert "op-3" not in extracted_ids
    assert "op-4" not in extracted_ids
    assert "op-5" not in extracted_ids


def test_extract_confirmed_operations_from_query_only_or_empty_ledger():
    """Un mensaje de solo consulta o con ledger vacío no produce operaciones confirmadas."""
    assert extract_confirmed_operations(None) == []
    assert extract_confirmed_operations([]) == []
    assert extract_confirmed_operations({"operation_ledger": []}) == []

    summary_text = format_confirmed_operations_text([])
    assert "Sin operaciones de modificación confirmadas" in summary_text


def test_extract_confirmed_operations_with_incomplete_references():
    """Maneja referencias incompletas o sin nombre sin romper ni filtrar datos incorrectos."""
    ledger_incomplete = [
        {
            "operation_id": "op-applied-no-name",
            "action_kind": "DELETE_CLASS",
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "44444444-4444-4444-4444-444444444444"}],
        },
        {
            "operation_id": "op-applied-no-refs",
            "action_kind": "MOVE_CLASS",
            "status": "applied",
            "entity_refs": [],
        },
        {
            "operation_id": "op-applied-malformed-ref",
            "action_kind": "CREATE_RELATION",
            "status": "applied",
            "entity_refs": ["not-a-dict", None, {"type": "relation", "name": "Factura_Cliente"}],
        },
    ]

    confirmed = extract_confirmed_operations(ledger_incomplete)
    assert len(confirmed) == 3

    assert confirmed[0].action_kind == "DELETE_CLASS"
    assert "Eliminación de clase" in confirmed[0].summary

    assert confirmed[1].action_kind == "MOVE_CLASS"
    assert "Movimiento de clase" in confirmed[1].summary

    assert confirmed[2].action_kind == "CREATE_RELATION"
    assert "Factura_Cliente" in confirmed[2].summary


def test_extract_confirmed_operations_respects_max_limit():
    """Respeta el límite máximo configurado de operaciones."""
    large_ledger = [
        {
            "operation_id": f"op-{i}",
            "action_kind": "CREATE_CLASS",
            "status": "applied",
            "entity_refs": [{"type": "class", "name": f"Class{i}"}],
        }
        for i in range(10)
    ]

    confirmed = extract_confirmed_operations(large_ledger, max_operations=3)
    assert len(confirmed) == 3


def test_confirmed_operation_to_dict():
    """to_dict produce diccionarios serializables limpios."""
    op = ConfirmedOperation(
        operation_id="op-1",
        action_kind="CREATE_CLASS",
        entity_refs=({"type": "class", "name": "Pedido"},),
        summary="Creación de clase: Pedido",
    )
    d = op.to_dict()
    assert d["operation_id"] == "op-1"
    assert d["action_kind"] == "CREATE_CLASS"
    assert d["entity_refs"] == [{"type": "class", "name": "Pedido"}]
    assert d["summary"] == "Creación de clase: Pedido"
