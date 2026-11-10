"""Validadores semánticos del modelo UML contra el estado actual del diagrama (Capa de Dominio).

Funciones puras y deterministas para detectar conflictos semánticos:
- Duplicación de relaciones idénticas
- Herencia reflexiva o cíclica
- Duplicación de atributos en una misma clase
- Existencia previa de clases
"""

from __future__ import annotations

from typing import Any, Sequence


def validate_relation_semantics(
    *,
    source: str,
    target: str,
    rel_type: str | None = None,
    existing_relations: Sequence[dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    """Verifica si la relación propuesta es válida contra las relaciones existentes."""
    s_clean = source.strip()
    t_clean = target.strip()

    # 1. Herencia a sí misma
    norm_type = (rel_type or "").upper()
    if norm_type in ("GENERALIZATION", "HERENCIA") and s_clean.casefold() == t_clean.casefold():
        return False, f"Una clase no puede heredar de sí misma ('{s_clean}')."

    # 2. Relación duplicada
    if existing_relations:
        for rel in existing_relations:
            r_src = str(rel.get("source", "")).strip().casefold()
            r_tgt = str(rel.get("target", "")).strip().casefold()
            r_type = str(rel.get("type", "")).strip().upper()

            # Mismo tipo y mismos extremos
            same_direction = r_src == s_clean.casefold() and r_tgt == t_clean.casefold()
            reverse_direction = r_src == t_clean.casefold() and r_tgt == s_clean.casefold()

            if (same_direction or (reverse_direction and norm_type in ("ASSOCIATION", "ASOCIACION"))) and (
                not norm_type or r_type == norm_type or not r_type
            ):
                return False, f"Ya existe una relación de tipo {norm_type or r_type} entre {s_clean} y {t_clean}."

    return True, None


def validate_inheritance_cycle(
    *,
    subclass: str,
    superclass: str,
    existing_inheritance: Sequence[dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    """Detecta si agregar una relación de herencia genera un ciclo en el árbol de generalización."""
    sub = subclass.strip().casefold()
    sup = superclass.strip().casefold()

    if sub == sup:
        return False, f"Jerarquía cíclica detectada: la clase '{subclass}' no puede ser su propio padre."

    if not existing_inheritance:
        return True, None

    # Construir grafo de adyacencia: hijo -> padres
    parents_map: dict[str, list[str]] = {}
    for item in existing_inheritance:
        child = str(item.get("subclass", "")).strip().casefold()
        parent = str(item.get("superclass", "")).strip().casefold()
        if child and parent:
            parents_map.setdefault(child, []).append(parent)

    # Agregar la arista propuesta: sub -> sup
    parents_map.setdefault(sub, []).append(sup)

    # Verificar si desde sup se puede alcanzar sub (recorrido hacia arriba)
    visited: set[str] = set()
    queue = [sup]

    while queue:
        current = queue.pop(0)
        if current == sub:
            return False, f"Jerarquía cíclica detectada: {subclass} no puede heredar de {superclass} porque generaría un ciclo."
        if current not in visited:
            visited.add(current)
            for ancestor in parents_map.get(current, []):
                if ancestor not in visited:
                    queue.append(ancestor)

    return True, None


def validate_attribute_duplicate(
    *,
    class_name: str,
    attribute_name: str,
    existing_attributes: Sequence[str] | None = None,
) -> tuple[bool, str | None]:
    """Verifica si la clase ya posee un atributo con ese nombre."""
    if not existing_attributes:
        return True, None

    attr_norm = attribute_name.strip().casefold()
    for existing in existing_attributes:
        if str(existing).strip().casefold() == attr_norm:
            return False, f"La clase {class_name} ya posee un atributo llamado '{attribute_name}'."

    return True, None


def validate_not_isolated_key_attribute(
    *,
    attribute_name: str,
    class_name: str | None = None,
) -> tuple[bool, str | None]:
    """Verifica si un atributo propuesto corresponde a una llave primaria o foránea que no debe crearse manualmente."""
    from app.modules.assistant.domain.dialog.key_attribute_rules import (
        is_primary_key_name,
        is_foreign_key_name,
        extract_referenced_entity_from_fk,
    )
    if is_primary_key_name(attribute_name, class_name):
        cls_ref = f" en '{class_name}'" if class_name else ""
        return (
            False,
            f"No es necesario crear la clave primaria '{attribute_name}'{cls_ref} porque las clases nacen con su llave primaria ('id') automáticamente.",
        )
    if is_foreign_key_name(attribute_name, class_name):
        ref = extract_referenced_entity_from_fk(attribute_name)
        hint = f" con '{ref.capitalize()}'" if ref else ""
        return (
            False,
            f"Las claves foráneas no se crean como atributos manuales ('{attribute_name}'). Se generan automáticamente al crear relaciones entre clases. Para generarla, crea una relación{hint}.",
        )
    return True, None

