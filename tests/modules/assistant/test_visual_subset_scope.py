from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)
from app.modules.assistant.domain.exceptions import AiProviderError
from app.modules.assistant.application.services.visual.visual_contracts import parse_visual_intent
import pytest


def test_normalizer_keeps_requested_fields_and_omits_derived_keys():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Producto y atributos, no relaciones",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "primary_key"},
                    {"name": "id_categoria", "data_type": "UUID", "key_kind": "foreign_key"},
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                ],
            },
            {"name": "Categoria", "attributes": [{"name": "nombre", "key_kind": "ordinary"}]},
        ),
        relations=({"source": "Producto", "target": "Categoria"},),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert [item["name"] for item in normalized["classes"]] == ["Producto"]
    assert [item["name"] for item in normalized["classes"][0]["attributes"]] == ["nombre"]
    assert normalized["relations"] == []
    assert len(normalized["derived_attributes"]) == 2


def test_exact_id_without_primary_marker_is_not_assumed_to_be_a_pk():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar Producto",
        scope={"classes": "all", "attributes": "all", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=({"name": "Producto", "attributes": [{"name": "id", "key_kind": "uncertain"}]},),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert normalized["classes"][0]["attributes"] == []
    assert any("marcador claro" in item for item in normalized["uncertainties"])


def test_ambiguous_key_marker_and_incompatible_visual_primary_key_block_mutation():
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar Producto",
        scope={"classes": "all", "attributes": "all", "relations": "all"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "key_kind": "primary_key", "data_type": "INTEGER"},
                    {"name": "codigo", "key_kind": "uncertain", "data_type": "TEXT"},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert normalized["classes"][0]["attributes"] == []
    assert any("PK UUID" in item for item in normalized["uncertainties"])
    assert any("no se pudo clasificar" in item for item in normalized["uncertainties"])


def test_scope_intersections_and_exclusions_are_strict():
    intent = parse_visual_intent(
        '{"mode":"mutate","needs_image":true,"visual_request":"Importar selección",'
        '"scope":{"classes":{"include":"all","exclude":["Categoria"]},'
        '"attributes":{"include":["nombre","precio"],"exclude":["precio"]},'
        '"relations":"none"},"independent_tasks":[],"clarification":null}'
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {"name": "Producto", "attributes": [{"name": "nombre"}, {"name": "precio"}]},
            {"name": "Categoria", "attributes": [{"name": "nombre"}]},
        ),
        relations=({"source": "Producto", "target": "Categoria"},),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert [item["name"] for item in normalized["classes"]] == ["Producto"]
    assert [item["name"] for item in normalized["classes"][0]["attributes"]] == ["nombre"]
    assert normalized["relations"] == []


def test_visual_intent_rejects_unknown_scope_selectors():
    with pytest.raises(AiProviderError):
        parse_visual_intent(
            '{"mode":"mutate","needs_image":true,"visual_request":"x",'
            '"scope":{"relations":{"execute":"all"}},"independent_tasks":[],"clarification":null}'
        )


def test_normalizer_preserves_needs_image_and_scope():
    """US3: El resultado normalizado preserva needs_image y el scope exacto de inclusión/exclusión."""
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar solo Usuario",
        scope={"classes": ["Usuario"], "attributes": {"include": "all", "exclude": ["clave"]}, "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {
                "name": "Usuario",
                "attributes": [
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "clave", "data_type": "TEXT", "key_kind": "ordinary"},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert normalized["needs_image"] is True
    assert normalized["scope"] == intent.scope
    assert [c["name"] for c in normalized["classes"]] == ["Usuario"]
    assert [a["name"] for a in normalized["classes"][0]["attributes"]] == ["nombre"]


def test_ambiguous_association_cardinality_produces_blocking_uncertainty():
    """US3: Asociaciones sin cardinalidad legible generan incertidumbre bloqueante."""
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar Autor y Libro con su relación",
        scope={"classes": "all", "attributes": "all", "relations": "all"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {"name": "Autor", "attributes": [{"name": "nombre", "key_kind": "ordinary"}]},
            {"name": "Libro", "attributes": [{"name": "titulo", "key_kind": "ordinary"}]},
        ),
        relations=(
            {
                "source": "Autor",
                "target": "Libro",
                "relation_type": "ASSOCIATION",
                "source_cardinality": None,  # Cardinalidad ilegible en la imagen
                "target_cardinality": "0..*",
            },
        ),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert any(
        "no tiene cardinalidad legible" in u and "Autor" in u and "Libro" in u
        for u in normalized["uncertainties"]
    )


def test_normalizer_maps_structural_head_to_canonical_roles():
    """T016: Mapeo de head_class a roles canónicos (source=todo/subclase, target=parte/superclase)."""
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar relaciones",
        scope={"classes": "all", "attributes": "none", "relations": "all"},
    )
    # Composición con extremos invertidos respecto a la cabeza
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {"name": "Habitación", "attributes": []},
            {"name": "Casa", "attributes": []},
        ),
        relations=(
            {
                "source": "Habitación",
                "target": "Casa",
                "relation_type": "COMPOSITION",
                "source_cardinality": None,
                "target_cardinality": None,
                "head_class": "Casa",
            },
        ),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert len(normalized["relations"]) == 1
    rel = normalized["relations"][0]
    # En composición, la cabeza (diamante) está en el todo (source)
    assert rel["source"] == "Casa"
    assert rel["target"] == "Habitación"


def test_normalizer_head_mismatch_creates_blocking_uncertainty():
    """T016: Cabeza ilegible o discordante genera incertidumbre bloqueante."""
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar herencia",
        scope={"classes": "all", "attributes": "none", "relations": "all"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {"name": "Caballo", "attributes": []},
            {"name": "Animal", "attributes": []},
        ),
        relations=(
            {
                "source": "Caballo",
                "target": "Animal",
                "relation_type": "GENERALIZATION",
                "source_cardinality": None,
                "target_cardinality": None,
                "head_class": "Desconocida",  # Cabeza no coincide con ninguno de los dos extremos
            },
        ),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert any(
        "cabeza" in u.lower() or "dirección" in u.lower() or "direccion" in u.lower()
        for u in normalized["uncertainties"]
    )


def test_normalizer_relations_none_strictly_excludes_all_relations():
    """T016: relations=none descarta todas las relaciones y genera 0 mutaciones de relación."""
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importar solo clases",
        scope={"classes": "all", "attributes": "none", "relations": "none"},
    )
    evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {"name": "Pedido", "attributes": []},
            {"name": "Producto", "attributes": []},
        ),
        relations=(
            {
                "source": "Pedido",
                "target": "Producto",
                "relation_type": "ASSOCIATION",
                "source_cardinality": "1",
                "target_cardinality": "0..*",
            },
        ),
        uncertainties=(),
    )

    normalized = normalize_visual_diagram(intent, evidence)

    assert normalized["relations"] == []


