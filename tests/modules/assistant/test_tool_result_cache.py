import pytest
from app.modules.assistant.application.services.execution.tool_result_cache import (
    ToolResultCache,
)


def test_tool_result_cache_hit_and_miss():
    cache = ToolResultCache()
    assert cache.hits == 0
    assert cache.misses == 0

    args = {"query": "Producto", "types": ["class"]}
    # Primer acceso: miss
    assert cache.get("search_diagram_elements", args) is None
    assert cache.misses == 1
    assert cache.hits == 0

    # Guardar en caché
    payload = {
        "status": "ok",
        "items": [
            {"type": "class", "id": "uuid-prod-123", "name": "Producto"}
        ],
    }
    cache.put("search_diagram_elements", args, payload)

    # Segundo acceso: hit
    cached = cache.get("search_diagram_elements", args)
    assert cached == payload
    assert cache.hits == 1
    assert cache.misses == 1

    # Acceso con orden de argumentos distinto (debe ser determinista)
    reordered_args = {"types": ["class"], "query": "Producto"}
    cached_reordered = cache.get("search_diagram_elements", reordered_args)
    assert cached_reordered == payload
    assert cache.hits == 2


def test_tool_result_cache_indexes_class_names():
    cache = ToolResultCache()
    args = {"query": "Cliente"}
    payload = {
        "status": "ok",
        "items": [
            {"type": "class", "id": "uuid-cliente-456", "name": "Cliente"},
            {"type": "attribute", "id": "uuid-attr-789", "name": "nombre"},
        ],
    }
    cache.put("search_diagram_elements", args, payload)

    assert cache.resolve_class_id("Cliente") == "uuid-cliente-456"
    assert cache.resolve_class_id("cliente") == "uuid-cliente-456"
    assert cache.resolve_class_id("CLIENTE") == "uuid-cliente-456"
    assert cache.resolve_class_id("Inexistente") is None


def test_tool_result_cache_invalidation_on_mutation():
    cache = ToolResultCache()
    search_args = {"query": "Pedido"}
    search_res = {
        "status": "ok",
        "items": [{"type": "class", "id": "uuid-pedido-1", "name": "Pedido"}],
    }
    cache.put("search_diagram_elements", search_args, search_res)
    assert cache.get("search_diagram_elements", search_args) is not None

    get_args = {"type": "class", "id": "uuid-pedido-1"}
    get_res = {"type": "class", "id": "uuid-pedido-1", "name": "Pedido", "detail": {}}
    cache.put("get_diagram_element", get_args, get_res)
    assert cache.get("get_diagram_element", get_args) is not None

    # Mutación que modifica Pedido
    mutation_args = {
        "actions": [
            {
                "kind": "CREATE_ATTRIBUTE",
                "class_id": "uuid-pedido-1",
                "name": "total",
            }
        ]
    }
    mutation_res = {
        "status": "applied",
        "results": [{"status": "applied", "entity_refs": [{"type": "attribute", "id": "attr-1"}]}],
    }

    cache.invalidate_for_mutation(mutation_args, mutation_res)

    # Las búsquedas de diagrama se invalidan porque cambió el modelo
    assert cache.get("search_diagram_elements", search_args) is None
    # El elemento modificado se invalida
    assert cache.get("get_diagram_element", get_args) is None
    # El mapeo de ID sigue disponible
    assert cache.resolve_class_id("Pedido") == "uuid-pedido-1"


def test_tool_result_cache_registers_newly_created_class():
    cache = ToolResultCache()
    mutation_args = {
        "actions": [
            {
                "kind": "CREATE_CLASS",
                "name": "Factura",
            }
        ]
    }
    mutation_res = {
        "status": "applied",
        "results": [
            {
                "status": "applied",
                "entity_refs": [
                    {"type": "class", "id": "uuid-factura-999"},
                    {"type": "attribute", "id": "uuid-attr-pk"},
                ],
            }
        ],
    }

    cache.invalidate_for_mutation(mutation_args, mutation_res)

    # La nueva clase Factura fue indexada automáticamente
    assert cache.resolve_class_id("Factura") == "uuid-factura-999"
    assert cache.resolve_class_id("factura") == "uuid-factura-999"


def test_tool_result_cache_ignores_uncacheable_tools():
    cache = ToolResultCache()
    args = {"actions": []}
    assert not cache.is_cacheable("apply_diagram_changes")
    assert cache.get("apply_diagram_changes", args) is None
    cache.put("apply_diagram_changes", args, {"status": "applied"})
    assert cache.get("apply_diagram_changes", args) is None
    assert cache.hits == 0
    assert cache.misses == 0
