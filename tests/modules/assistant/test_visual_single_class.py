from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
    parse_visual_intent,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)


def test_visual_subset_selects_one_named_class_and_excludes_neighbors_and_relations():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Solo Producto y sus atributos",
        scope={
            "classes": ["Producto"],
            "attributes": "all",
            "relations": "none",
        },
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {"name": "Producto", "attributes": [{"name": "nombre", "key_kind": "ordinary"}]},
            {"name": "Categoria", "attributes": [{"name": "nombre", "key_kind": "ordinary"}]},
        ),
        relations=({"name": "pertenece", "source": "Producto", "target": "Categoria"},),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert [item["name"] for item in normalized["classes"]] == ["Producto"]
    assert [item["name"] for item in normalized["classes"][0]["attributes"]] == ["nombre"]
    assert normalized["relations"] == []


def test_ambiguous_visual_class_selection_requests_clarification_before_evidence():
    intent = parse_visual_intent(
        '{"mode":"clarify","needs_image":false,"visual_request":"",'
        '"scope":{},"independent_tasks":[],"clarification":'
        '"Hay dos clases llamadas Producto; ¿cuál quieres?","requested_mode":"mutate"}'
    )

    assert intent.mode == "clarify"
    assert intent.requested_mode == "mutate"
    assert "dos clases" in intent.clarification


def test_visual_descriptor_keeps_only_the_vision_resolved_class():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Solo la clase resaltada en rojo",
        scope={"classes": "all", "attributes": "none", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=({"name": "Producto", "attributes": []},),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert [item["name"] for item in normalized["classes"]] == ["Producto"]
    assert normalized["classes"][0]["attributes"] == []


def test_explicit_relation_scope_includes_its_endpoint_without_its_attributes():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Incluye Producto y su relación con Categoria",
        scope={
            "classes": ["Producto"],
            "attributes": "all",
            "relations": ["Producto-Categoria"],
        },
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {"name": "Producto", "attributes": [{"name": "nombre", "key_kind": "ordinary"}]},
            {"name": "Categoria", "attributes": [{"name": "descripcion", "key_kind": "ordinary"}]},
        ),
        relations=(
            {
                "name": "Producto-Categoria",
                "source": "Producto",
                "target": "Categoria",
                "relation_type": "ASSOCIATION",
                "source_cardinality": "0..*",
                "target_cardinality": "1",
            },
        ),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert [item["name"] for item in normalized["classes"]] == ["Producto", "Categoria"]
    assert [item["name"] for item in normalized["classes"][0]["attributes"]] == ["nombre"]
    assert normalized["classes"][1]["attributes"] == []
    assert len(normalized["relations"]) == 1
