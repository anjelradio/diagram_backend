"""Pruebas unitarias para el servicio de preparación de solicitudes RequestReadiness."""

from typing import Any
import pytest

from app.modules.assistant.application.services.continuation.request_readiness import (
    RequestReadiness,
    ReadinessReport,
)


def test_colloquial_relation_request_asks_for_missing_type_before_mutating():
    report = RequestReadiness().evaluate_initial_request(
        "crea una clase llamada Escoba y quiero que las relaciones con la clase árbol"
    )
    assert report is not None and not report.is_ready
    assert {fact["key"]: fact["value"] for fact in report.resolved_facts}[
        "relation.source_class"
    ] == "Escoba"
    assert {fact["key"]: fact["value"] for fact in report.resolved_facts}[
        "relation.target_class"
    ] == "árbol"
    assert any(field["key"] == "relation.type" for field in report.missing_critical_fields)


def test_create_class_readiness_applies_defaults_without_asking_for_attributes_or_relations():
    readiness = RequestReadiness()

    # Creación de clase con nombre explícito
    report = readiness.evaluate_class_creation(name="Factura")
    assert report.is_ready is True
    assert len(report.missing_critical_fields) == 0

    # El asistente necesita un nombre aunque la UI manual admita un default.
    report_unnamed = readiness.evaluate_class_creation(name=None)
    assert report_unnamed.is_ready is False
    assert [field["key"] for field in report_unnamed.missing_critical_fields] == ["class.name"]

    # Jamás debe marcar atributos o relaciones como campos críticos al crear clase
    for field in report.missing_fields:
        assert "attribute" not in field["key"]
        assert "relation" not in field["key"]


def test_create_attribute_requires_target_class_and_name_but_defaults_type_and_nullable():
    readiness = RequestReadiness()

    # Falta clase destino
    report_no_class = readiness.evaluate_attribute_creation(
        target_class=None, name="precio", data_type=None, nullable=None
    )
    assert report_no_class.is_ready is False
    assert any(f["key"] == "attribute.target_class" and f["critical"] for f in report_no_class.missing_critical_fields)

    # Falta nombre de atributo
    report_no_name = readiness.evaluate_attribute_creation(
        target_class="Producto", name=None, data_type=None, nullable=None
    )
    assert report_no_name.is_ready is False
    assert any(f["key"] == "attribute.name" and f["critical"] for f in report_no_name.missing_critical_fields)

    # Con clase y nombre, pero sin tipo ni nulabilidad: DEBE estar ready con defaults
    report_ready = readiness.evaluate_attribute_creation(
        target_class="Producto", name="precio", data_type=None, nullable=None
    )
    assert report_ready.is_ready is True
    assert len(report_ready.missing_critical_fields) == 0
    # Verifica que data_type y nullable no se exijan como críticos
    for field in report_ready.missing_fields:
        assert not field.get("critical", False)


def test_create_association_requires_both_endpoints_and_cardinalities():
    readiness = RequestReadiness()

    # Falta tipo de relación
    report_missing_type = readiness.evaluate_relation(
        source_class="Producto",
        target_class="Categoria",
        relation_type=None,
    )
    assert report_missing_type.is_ready is False
    assert any(f["key"] == "relation.type" for f in report_missing_type.missing_critical_fields)

    # Asociación con tipo pero sin cardinalidades
    report_missing_card = readiness.evaluate_relation(
        source_class="Producto",
        target_class="Categoria",
        relation_type="ASSOCIATION",
        source_cardinality=None,
        target_cardinality=None,
    )
    assert report_missing_card.is_ready is False
    assert any("cardinalit" in f["key"] for f in report_missing_card.missing_critical_fields)

    # Usuario indica "uno a muchos" genérico pero no qué extremo es cuál
    report_partial_card = readiness.evaluate_relation(
        source_class="Producto",
        target_class="Categoria",
        relation_type="ASSOCIATION",
        generic_cardinality="one_to_many",
        source_cardinality=None,
        target_cardinality=None,
    )
    assert report_partial_card.is_ready is False
    # Debe formular pregunta específica por cada extremo
    assert any("endpoint_cardinalities" in f["key"] for f in report_partial_card.missing_critical_fields)

    # Con ambos extremos y cardinalidades canónicas
    report_ready = readiness.evaluate_relation(
        source_class="Producto",
        target_class="Categoria",
        relation_type="ASSOCIATION",
        source_cardinality="0..*",
        target_cardinality="1",
    )
    assert report_ready.is_ready is True
    assert len(report_ready.missing_critical_fields) == 0


def test_create_structural_relation_requires_semantic_roles_and_forbids_cardinalities():
    readiness = RequestReadiness()

    # Composición sin definir cuál es el todo y cuál la parte
    report_no_roles = readiness.evaluate_relation(
        source_class="Casa",
        target_class="Habitacion",
        relation_type="COMPOSITION",
        whole_class=None,
        part_class=None,
    )
    assert report_no_roles.is_ready is False
    assert any(f["key"] == "relation.direction" or "role" in f["key"] for f in report_no_roles.missing_critical_fields)

    # Composición con roles definidos
    report_ready = readiness.evaluate_relation(
        source_class="Casa",
        target_class="Habitacion",
        relation_type="COMPOSITION",
        whole_class="Casa",
        part_class="Habitacion",
    )
    assert report_ready.is_ready is True
    assert len(report_ready.missing_critical_fields) == 0

    # No debe solicitar cardinalidades para relaciones estructurales
    for field in report_ready.missing_fields:
        assert "cardinality" not in field["key"]


def test_grouped_questions_formatting_for_multiple_missing_fields():
    readiness = RequestReadiness()

    missing_fields = [
        {
            "key": "relation.type",
            "action": "CREATE_RELATION",
            "critical": True,
            "question": "¿Qué tipo de relación deseas entre Producto y Categoría?",
        },
        {
            "key": "relation.endpoint_cardinalities",
            "action": "CREATE_RELATION",
            "critical": True,
            "question": "¿Cuáles son las cardinalidades en cada extremo?",
        },
    ]

    grouped_question = readiness.format_grouped_question(missing_fields)
    assert "¿Qué tipo de relación deseas" in grouped_question
    assert "¿Cuáles son las cardinalidades" in grouped_question


def test_request_readiness_facts_merging_and_limit_enforcement():
    readiness = RequestReadiness(max_facts=20, max_questions=20)

    initial_facts = [{"key": "relation.source_class", "value": "Producto"}]
    new_facts = [{"key": "relation.target_class", "value": "Categoria"}]

    merged = readiness.merge_facts(initial_facts, new_facts)
    assert len(merged) == 2
    assert merged[0]["value"] == "Producto"
    assert merged[1]["value"] == "Categoria"

    # Actualizar un hecho existente conserva la última versión
    updated_facts = [{"key": "relation.source_class", "value": "ProductoVenta"}]
    merged_updated = readiness.merge_facts(merged, updated_facts)
    assert len(merged_updated) == 2
    source_fact = next(f for f in merged_updated if f["key"] == "relation.source_class")
    assert source_fact["value"] == "ProductoVenta"

    # Superar límite de 20 hechos
    overflow_facts = [{"key": f"extra_{i}", "value": f"val_{i}"} for i in range(25)]
    merged_overflow = readiness.merge_facts([], overflow_facts)
    assert len(merged_overflow) <= 20


def test_relation_without_type_blocks_readiness_and_preserves_endpoints():
    readiness = RequestReadiness()
    report = readiness.evaluate_relation(
        source_class="Pedido",
        target_class="Cliente",
        relation_type=None,
    )
    assert report.is_ready is False
    assert any(f["key"] == "relation.type" for f in report.missing_critical_fields)
    facts_dict = {f["key"]: f["value"] for f in report.resolved_facts}
    assert facts_dict["relation.source_class"] == "Pedido"
    assert facts_dict["relation.target_class"] == "Cliente"


def test_relation_partial_cardinality_accumulates_known_and_asks_missing_endpoint():
    readiness = RequestReadiness()

    # Fuente definida, falta destino
    report_source_only = readiness.evaluate_relation(
        source_class="Pedido",
        target_class="Cliente",
        relation_type="ASSOCIATION",
        source_cardinality="1",
        target_cardinality=None,
    )
    assert report_source_only.is_ready is False
    assert any(f["key"] == "relation.target_cardinality" for f in report_source_only.missing_critical_fields)
    assert not any(f["key"] == "relation.source_cardinality" for f in report_source_only.missing_critical_fields)
    facts_src = {f["key"]: f["value"] for f in report_source_only.resolved_facts}
    assert facts_src["relation.source_cardinality"] == "1"

    # Destino definido, falta origen
    report_target_only = readiness.evaluate_relation(
        source_class="Pedido",
        target_class="Cliente",
        relation_type="ASSOCIATION",
        source_cardinality=None,
        target_cardinality="0..*",
    )
    assert report_target_only.is_ready is False
    assert any(f["key"] == "relation.source_cardinality" for f in report_target_only.missing_critical_fields)
    assert not any(f["key"] == "relation.target_cardinality" for f in report_target_only.missing_critical_fields)
    facts_tgt = {f["key"]: f["value"] for f in report_target_only.resolved_facts}
    assert facts_tgt["relation.target_cardinality"] == "0..*"


def test_relation_structural_roles_whole_part_and_generalization_partial():
    readiness = RequestReadiness()

    # Composición: sólo se especificó el todo
    report_comp = readiness.evaluate_relation(
        source_class="Factura",
        target_class="Item",
        relation_type="COMPOSITION",
        whole_class="Factura",
        part_class=None,
    )
    assert report_comp.is_ready is False
    assert any(f["key"] == "relation.part" for f in report_comp.missing_critical_fields)
    facts_comp = {f["key"]: f["value"] for f in report_comp.resolved_facts}
    assert facts_comp["relation.whole"] == "Factura"

    # Generalización: sólo se especificó superclase
    report_gen = readiness.evaluate_relation(
        source_class="Vehiculo",
        target_class="Auto",
        relation_type="GENERALIZATION",
        superclass="Vehiculo",
        subclass=None,
    )
    assert report_gen.is_ready is False
    assert any(f["key"] == "relation.subclass" for f in report_gen.missing_critical_fields)
    facts_gen = {f["key"]: f["value"] for f in report_gen.resolved_facts}
    assert facts_gen["relation.superclass"] == "Vehiculo"


def test_request_readiness_handles_malformed_facts_and_corrupt_entries_safely():
    readiness = RequestReadiness()

    # merge_facts soporta elementos no dict y entradas sin clave 'key'
    corrupt_entries = [None, 123, "string", {}, {"key": "relation.source_class", "value": "A"}]
    merged = readiness.merge_facts(corrupt_entries, [{"key": "relation.target_class", "value": "B"}, None])
    assert len(merged) == 2
    keys = {f["key"] for f in merged}
    assert keys == {"relation.source_class", "relation.target_class"}

    # compute_remaining_missing soporta missing corruptos y resolved corruptos
    candidate_missing = [None, "invalid", {}, {"key": "relation.type", "critical": True}]
    resolved_corrupt = [None, {}, {"key": "relation.source_class", "value": "A"}]
    remaining = readiness.compute_remaining_missing(candidate_missing, resolved_corrupt)
    assert len(remaining) == 1
    assert remaining[0]["key"] == "relation.type"


def test_compute_remaining_missing_refines_endpoint_cardinalities_when_one_provided():
    readiness = RequestReadiness()

    candidate = [{"key": "relation.endpoint_cardinalities", "critical": True}]
    resolved = [{"key": "relation.source_cardinality", "value": "1"}]

    refined = readiness.compute_remaining_missing(candidate, resolved)
    assert len(refined) == 1
    assert refined[0]["key"] == "relation.target_cardinality"

