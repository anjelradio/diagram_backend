"""Caché efímero de consultas de lectura del diagrama durante la ejecución de un plan."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CACHEABLE_TOOLS = frozenset({"search_diagram_elements", "get_diagram_element"})


class ToolResultCache:
    """Caché con alcance por ejecución de plan para evitar consultas repetidas al diagrama."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._class_name_to_id: dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @staticmethod
    def is_cacheable(tool_name: str) -> bool:
        return tool_name in CACHEABLE_TOOLS

    def cache_key(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Genera una clave determinista serializada para argumentos de lectura."""
        try:
            serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            serialized = str(sorted(arguments.items()))
        return f"{tool_name}:{serialized}"

    def get(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Devuelve el resultado almacenado si existe para tool y arguments."""
        if not self.is_cacheable(tool_name):
            return None
        key = self.cache_key(tool_name, arguments)
        result = self._cache.get(key)
        if result is not None:
            self._hits += 1
            logger.info("ToolResultCache HIT (tool=%s, key=%s)", tool_name, key)
            return result
        self._misses += 1
        return None

    def put(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Almacena el resultado de una consulta exitosa e indexa entidades conocidas."""
        if not self.is_cacheable(tool_name):
            return
        key = self.cache_key(tool_name, arguments)
        self._cache[key] = result
        self._index_entities(tool_name, arguments, result)

    def _index_entities(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        if tool_name == "search_diagram_elements":
            for item in result.get("items", []):
                if isinstance(item, dict) and item.get("type") == "class":
                    name = item.get("name")
                    cid = item.get("id")
                    if isinstance(name, str) and isinstance(cid, str):
                        self._class_name_to_id[name.strip().lower()] = cid
        elif tool_name == "get_diagram_element":
            if result.get("type") == "class":
                name = result.get("name")
                cid = result.get("id")
                if isinstance(name, str) and isinstance(cid, str):
                    self._class_name_to_id[name.strip().lower()] = cid

    def seed_class(self, name: str, class_id: str) -> None:
        """Registra una clase conocida previamente (e.g., desde RoomState o creación previa)."""
        if name and class_id:
            self._class_name_to_id[name.strip().lower()] = str(class_id)

    def resolve_class_id(self, class_name: str) -> str | None:
        """Devuelve el ID de una clase si ya fue encontrada o creada durante el plan."""
        return self._class_name_to_id.get(class_name.strip().lower())

    def get_known_classes(self) -> dict[str, str]:
        """Devuelve una copia del mapeo clase -> ID conocido."""
        return dict(self._class_name_to_id)

    def register_mutation_results(self, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Indexa clases recién creadas a partir de los resultados de apply_diagram_changes."""
        actions = arguments.get("actions", [])
        action_results = result.get("results", [])
        for action, act_res in zip(actions, action_results):
            if not isinstance(action, dict) or not isinstance(act_res, dict):
                continue
            if action.get("kind") == "CREATE_CLASS" and act_res.get("status") == "applied":
                name = action.get("name")
                for ref in act_res.get("entity_refs", []):
                    if isinstance(ref, dict) and ref.get("type") == "class" and ref.get("id"):
                        if name:
                            self.seed_class(name, ref["id"])

    def invalidate_for_mutation(self, arguments: dict[str, Any], result: dict[str, Any] | None = None) -> None:
        """Invalida búsquedas previas de diagrama tras una mutación aplicada.

        Cualquier mutación (crear/modificar/borrar) altera la lista de elementos,
        por lo que search_diagram_elements se invalida para no servir datos obsoletos.
        get_diagram_element se invalida para los IDs de los elementos afectados.
        """
        # Limpiar todas las búsquedas de elementos (porque el diagrama cambió)
        search_keys = [k for k in self._cache if k.startswith("search_diagram_elements:")]
        for k in search_keys:
            del self._cache[k]

        actions = arguments.get("actions", [])
        for action in actions:
            if not isinstance(action, dict):
                continue
            kind = action.get("kind", "")
            # Si se borra o renombra una clase, removerla del mapa
            if kind in ("DELETE_CLASS", "MODIFY_CLASS"):
                name = action.get("name") or action.get("target_name")
                if name:
                    self._class_name_to_id.pop(name.strip().lower(), None)
            # Si hay un ID de elemento afectado, invalidar su get_diagram_element
            target_id = (
                action.get("class_id")
                or action.get("attribute_id")
                or action.get("relation_id")
                or action.get("id")
            )
            if target_id:
                target_str = str(target_id)
                get_keys = [
                    k for k in self._cache
                    if k.startswith("get_diagram_element:") and target_str in k
                ]
                for k in get_keys:
                    del self._cache[k]

        # Si se crearon clases en esta mutación, registrarlas
        if result is not None:
            self.register_mutation_results(arguments, result)
