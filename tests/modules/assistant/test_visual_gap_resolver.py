import pytest
from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
)
from app.modules.assistant.application.services.visual.visual_gap_resolver import (
    VisualGapResolver,
)


@pytest.mark.anyio
async def test_resolver_discards_id_and_fk_attributes_silently():
    resolver = VisualGapResolver()
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="crea Producto",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "none"},
    )
    raw_evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "primary_key"},
                    {"name": "id_producto", "data_type": "INTEGER", "key_kind": "uncertain"},
                    {"name": "categoria_id", "data_type": "INTEGER", "key_kind": "foreign_key"},
                    {"name": "fk_proveedor", "data_type": "INTEGER", "key_kind": "foreign_key"},
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "precio", "data_type": "DECIMAL", "key_kind": "ordinary"},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )
    normalized = {
        "supported": True,
        "diagram_kind": "ERD",
        "needs_image": True,
        "scope": intent.scope,
        "classes": [
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "primary_key"},
                    {"name": "id_producto", "data_type": "INTEGER", "key_kind": "uncertain"},
                    {"name": "categoria_id", "data_type": "INTEGER", "key_kind": "foreign_key"},
                    {"name": "fk_proveedor", "data_type": "INTEGER", "key_kind": "foreign_key"},
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "precio", "data_type": "DECIMAL", "key_kind": "ordinary"},
                ],
            }
        ],
        "relations": [],
        "derived_attributes": [],
        "uncertainties": [
            "Se observó un atributo llamado `id` sin marcador claro de PK; aclara si corresponde a la clave primaria existente.",
            "La FK visual `categoria_id` de `Producto` no tiene una relación inequívoca asociada; no se materializará como atributo.",
        ],
    }

    resolved_intent, payload = await resolver.resolve(
        prompt="quiero que crees la clase producto de la imagen",
        intent=intent,
        evidence=raw_evidence,
        normalized_evidence=normalized,
    )

    producto_class = payload["classes"][0]
    attribute_names = [a["name"] for a in producto_class["attributes"]]
    assert attribute_names == ["nombre", "precio"]

    # Verificamos que las llaves se registraron en derived_attributes
    derived_names = {d["attribute"] for d in payload["derived_attributes"]}
    assert "id" in derived_names
    assert "id_producto" in derived_names
    assert "categoria_id" in derived_names
    assert "fk_proveedor" in derived_names

    # Verificamos que las incertidumbres de id y fk fueron podadas
    assert len(payload["uncertainties"]) == 0


@pytest.mark.anyio
async def test_resolver_canonicalizes_sql_data_types_and_infers():
    resolver = VisualGapResolver()
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="crea Factura",
        scope={"classes": ["Factura"], "attributes": "all", "relations": "none"},
    )
    raw_evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Factura",
                "attributes": [
                    {"name": "numero", "data_type": "VARCHAR(50)", "key_kind": "ordinary"},
                    {"name": "lineas", "data_type": "INT4", "key_kind": "ordinary"},
                    {"name": "subtotal", "data_type": "NUMERIC(12,2)", "key_kind": "ordinary"},
                    {"name": "emitido_en", "data_type": "DATETIME", "key_kind": "ordinary"},
                    {"name": "es_valida", "data_type": "BIT", "key_kind": "ordinary"},
                    {"name": "fecha_emision", "data_type": None, "key_kind": "ordinary"},
                    {"name": "monto_total", "data_type": None, "key_kind": "ordinary"},
                    {"name": "campo_desconocido", "data_type": None, "key_kind": "ordinary"},
                ],
            },
        ),
        relations=(),
        uncertainties=(),
    )
    normalized = {
        "supported": True,
        "diagram_kind": "ERD",
        "classes": [dict(raw_evidence.classes[0])],
        "relations": [],
        "derived_attributes": [],
        "uncertainties": [
            "El tipo del atributo `numero` (VARCHAR(50)) no pertenece a los tipos admitidos; pide precisión."
        ],
    }

    _, payload = await resolver.resolve(
        prompt="crea la clase factura",
        intent=intent,
        evidence=raw_evidence,
        normalized_evidence=normalized,
    )

    attrs = {a["name"]: a["data_type"] for a in payload["classes"][0]["attributes"]}
    assert attrs["numero"] == "TEXT"
    assert attrs["lineas"] == "INTEGER"
    assert attrs["subtotal"] == "DECIMAL"
    assert attrs["emitido_en"] == "TIMESTAMP"
    assert attrs["es_valida"] == "BOOLEAN"
    assert attrs["fecha_emision"] == "DATE"
    assert attrs["monto_total"] == "DECIMAL"
    assert attrs["campo_desconocido"] is None  # Sin tipo permitido en dominio

    assert len(payload["uncertainties"]) == 0


@pytest.mark.anyio
async def test_resolver_expands_connected_classes_with_full_attributes():
    resolver = VisualGapResolver()
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="crea Producto y sus relaciones",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "all"},
    )
    raw_evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(
            {
                "name": "Producto",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "primary_key"},
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "categoria_id", "data_type": "INTEGER", "key_kind": "foreign_key"},
                ],
            },
            {
                "name": "Categoria",
                "attributes": [
                    {"name": "id", "data_type": "UUID", "key_kind": "primary_key"},
                    {"name": "descripcion", "data_type": "TEXT", "key_kind": "ordinary"},
                    {"name": "activo", "data_type": "BOOLEAN", "key_kind": "ordinary"},
                ],
            },
            {
                "name": "NoRelacionada",
                "attributes": [
                    {"name": "dato", "data_type": "TEXT", "key_kind": "ordinary"},
                ],
            },
        ),
        relations=(
            {
                "source": "Producto",
                "target": "Categoria",
                "relation_type": "ASSOCIATION",
                "source_cardinality": None,
                "target_cardinality": None,
            },
        ),
        uncertainties=(),
    )
    # En normalización previa, Categoria se metió vacía porque no estaba en classes
    normalized = {
        "supported": True,
        "diagram_kind": "ERD",
        "classes": [
            {
                "name": "Producto",
                "attributes": [
                    {"name": "nombre", "data_type": "TEXT", "key_kind": "ordinary"},
                ],
            },
            {
                "name": "Categoria",
                "attributes": [],
            },
        ],
        "relations": [
            {
                "source": "Producto",
                "target": "Categoria",
                "relation_type": "ASSOCIATION",
                "source_cardinality": None,
                "target_cardinality": None,
            }
        ],
        "derived_attributes": [],
        "uncertainties": [
            "La relación entre `Producto` y `Categoria` no tiene cardinalidad legible; aclara sus cardinalidades antes de mutar."
        ],
    }

    resolved_intent, payload = await resolver.resolve(
        prompt="quiero que crees la clase producto y sus relaciones de la imagen",
        intent=intent,
        evidence=raw_evidence,
        normalized_evidence=normalized,
    )

    # Verifica que ambas clases están presentes y Categoria recuperó sus atributos
    classes_by_name = {c["name"]: c for c in payload["classes"]}
    assert "Producto" in classes_by_name
    assert "Categoria" in classes_by_name
    assert "NoRelacionada" not in classes_by_name

    categoria_attrs = [a["name"] for a in classes_by_name["Categoria"]["attributes"]]
    assert categoria_attrs == ["descripcion", "activo"]

    # Verifica que el scope del intent ahora incluye Categoria
    assert "Categoria" in resolved_intent.scope["classes"]
    assert "Producto" in resolved_intent.scope["classes"]

    # Verifica deducción de cardinalidad de relación basada en que Producto tenía categoria_id
    rel = payload["relations"][0]
    assert rel["source_cardinality"] == "0..*"
    assert rel["target_cardinality"] == "1"

    # La incertidumbre de cardinalidad fue podada
    assert len(payload["uncertainties"]) == 0


@pytest.mark.anyio
async def test_resolver_deduces_recursive_and_structural_relations():
    resolver = VisualGapResolver()
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="crea diagrama",
        scope={"classes": "all", "attributes": "all", "relations": "all"},
    )
    raw_evidence = VisualEvidence(
        supported=True,
        diagram_kind="UML_CLASS",
        classes=(
            {"name": "Empleado", "attributes": [{"name": "nombre", "data_type": "TEXT"}]},
            {"name": "Orden", "attributes": []},
            {"name": "Item", "attributes": []},
        ),
        relations=(
            {
                "source": "Empleado",
                "target": "Empleado",
                "relation_type": "ASSOCIATION",
                "source_cardinality": None,
                "target_cardinality": None,
            },
            {
                "source": "Orden",
                "target": "Item",
                "relation_type": "COMPOSITION",
                "head_class": None,
            },
        ),
        uncertainties=(),
    )
    normalized = {
        "supported": True,
        "diagram_kind": "UML_CLASS",
        "classes": [dict(c) for c in raw_evidence.classes],
        "relations": [dict(r) for r in raw_evidence.relations],
        "derived_attributes": [],
        "uncertainties": [
            "La relación entre `Empleado` y `Empleado` no tiene cardinalidad legible.",
            "No se pudo leer con certeza la dirección o cabeza de la relación `COMPOSITION` entre `Orden` e `Item`.",
        ],
    }

    _, payload = await resolver.resolve(
        prompt="recrea todo el diagrama de la imagen",
        intent=intent,
        evidence=raw_evidence,
        normalized_evidence=normalized,
    )

    relations = payload["relations"]
    recursive_rel = next(r for r in relations if r["source"] == "Empleado" and r["target"] == "Empleado")
    assert recursive_rel["source_cardinality"] == "0..1"
    assert recursive_rel["target_cardinality"] == "0..*"

    composition_rel = next(r for r in relations if r["relation_type"] == "COMPOSITION")
    assert composition_rel["head_class"] == "Orden"

    # Incertidumbres resueltas
    assert len(payload["uncertainties"]) == 0


@pytest.mark.anyio
async def test_resolver_preserves_unresolvable_critical_uncertainties():
    resolver = VisualGapResolver()
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="crea Producto",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "none"},
    )
    raw_evidence = VisualEvidence(
        supported=True,
        diagram_kind="ERD",
        classes=(),
        relations=(),
        uncertainties=(),
    )
    normalized = {
        "supported": True,
        "diagram_kind": "ERD",
        "classes": [],
        "relations": [],
        "derived_attributes": [],
        "uncertainties": [
            "La imagen contiene varias clases llamadas `Producto`; indica cuál corresponde.",
            "Falta una cardinalidad necesaria para establecer la relación de asociación.",
        ],
    }

    _, payload = await resolver.resolve(
        prompt="crea producto",
        intent=intent,
        evidence=raw_evidence,
        normalized_evidence=normalized,
    )

    # La de cardinalidad se poda, pero la de ambigüedad de nombre se PRESERVA
    assert len(payload["uncertainties"]) == 1
    assert "varias clases llamadas `Producto`" in payload["uncertainties"][0]
