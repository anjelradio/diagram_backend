"""Reglas deterministas de clasificación e ignorado de atributos clave (PK y FK).

En el metamodelo UML/Relacional del sistema:
1. Toda clase nace con su clave primaria (`id: UUID`). Los atributos que actúan como PK
   no deben crearse manualmente como atributos secundarios.
2. Toda clave foránea nace exclusivamente de la materialización de relaciones entre clases.
   Los atributos que actúan como FK no deben crearse como atributos secundarios ordinarios.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _normalize_name(val: str | None) -> str:
    if not val or not isinstance(val, str):
        return ""
    cleaned = val.strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", cleaned)
        if unicodedata.category(c) != "Mn"
    )


# Patrones inequívocos de llaves primarias
_EXACT_PK_NAMES: frozenset[str] = frozenset({
    "id",
    "uuid",
    "pk",
    "guid",
    "id_pk",
})

# Frases literales que representan intención de llave foránea o primaria
_LITERAL_FK_TERMS: frozenset[str] = frozenset({
    "llave_foranea",
    "llave foranea",
    "foreign_key",
    "foreign key",
    "fk",
})

_LITERAL_PK_TERMS: frozenset[str] = frozenset({
    "llave_primaria",
    "llave primaria",
    "primary_key",
    "primary key",
    "pk",
})

_FK_PREFIX_PATTERN = re.compile(r"^fk[_\-\s].+$", re.IGNORECASE)
_FK_SUFFIX_PATTERN = re.compile(r"^.+[_\-\s]fk$", re.IGNORECASE)

_ID_PREFIX_PATTERN = re.compile(r"^id[_\-\s]([a-z0-9_]+)$", re.IGNORECASE)
_ID_SUFFIX_PATTERN = re.compile(r"^([a-z0-9_]+)[_\-\s]id$", re.IGNORECASE)


def is_primary_key_name(name: str | None, class_name: str | None = None) -> bool:
    """Determina si un nombre de atributo corresponde a la clave primaria de la clase.

    Ejemplos:
        `id` -> True
        `uuid` -> True
        `pk` -> True
        `producto_id` en clase `Producto` -> True
        `id_producto` en clase `Producto` -> True
        `pk_producto` en clase `Producto` -> True
    """
    clean_attr = _normalize_name(name)
    if not clean_attr:
        return False

    if clean_attr in _EXACT_PK_NAMES or clean_attr in _LITERAL_PK_TERMS:
        return True

    if class_name:
        clean_cls = _normalize_name(class_name)
        if clean_cls:
            # Coincidencia con id_<clase> o <clase>_id o pk_<clase>
            self_pk_candidates = {
                f"id_{clean_cls}",
                f"{clean_cls}_id",
                f"pk_{clean_cls}",
                f"{clean_cls}_pk",
                f"id{clean_cls}",
                f"{clean_cls}id",
            }
            if clean_attr in self_pk_candidates:
                return True

    return False


def is_foreign_key_name(name: str | None, class_name: str | None = None) -> bool:
    """Determina si un nombre de atributo corresponde por convención a una clave foránea.

    Ejemplos:
        `categoria_id` en clase `Producto` -> True
        `id_categoria` en clase `Producto` -> True
        `fk_usuario` -> True
        `producto_id` en clase `Producto` -> False (es su propia PK)
    """
    clean_attr = _normalize_name(name)
    if not clean_attr:
        return False

    # Términos literales
    if clean_attr in _LITERAL_FK_TERMS:
        return True

    # Si es exactamente la PK de la propia clase, NO es FK
    if is_primary_key_name(name, class_name):
        return False

    # Prefijos/Sufijos explícitos fk_ o _fk
    if _FK_PREFIX_PATTERN.match(clean_attr) or _FK_SUFFIX_PATTERN.match(clean_attr):
        return True

    # Prefijo id_<otra_entidad> (ej. id_categoria, id_cliente)
    prefix_match = _ID_PREFIX_PATTERN.match(clean_attr)
    if prefix_match:
        ref_entity = prefix_match.group(1)
        if class_name and _normalize_name(class_name) == ref_entity:
            return False  # Es su propia PK
        return True

    # Sufijo <otra_entidad>_id (ej. categoria_id, usuario_id)
    suffix_match = _ID_SUFFIX_PATTERN.match(clean_attr)
    if suffix_match:
        ref_entity = suffix_match.group(1)
        if class_name and _normalize_name(class_name) == ref_entity:
            return False  # Es su propia PK
        return True

    return False


def is_any_key_name(name: str | None, class_name: str | None = None) -> bool:
    """Retorna True si el nombre es una clave primaria o una clave foránea."""
    return is_primary_key_name(name, class_name) or is_foreign_key_name(name, class_name)


def extract_referenced_entity_from_fk(name: str | None) -> str | None:
    """Extrae el nombre tentativo de la clase referenciada por un atributo FK.

    Ejemplos:
        `categoria_id` -> "categoria"
        `id_categoria` -> "categoria"
        `fk_cliente`   -> "cliente"
    """
    clean = _normalize_name(name)
    if not clean:
        return None

    if _FK_PREFIX_PATTERN.match(clean):
        return re.sub(r"^fk[_\-\s]", "", clean).strip()
    if _FK_SUFFIX_PATTERN.match(clean):
        return re.sub(r"[_\-\s]fk$", "", clean).strip()

    prefix_m = _ID_PREFIX_PATTERN.match(clean)
    if prefix_m:
        return prefix_m.group(1).strip()

    suffix_m = _ID_SUFFIX_PATTERN.match(clean)
    if suffix_m:
        return suffix_m.group(1).strip()

    return None


def filter_secondary_attributes(
    attributes: list[dict[str, Any] | str],
    class_name: str | None = None,
) -> tuple[list[dict[str, Any] | str], list[dict[str, Any] | str]]:
    """Separa una lista de atributos en atributos ordinarios válidos y atributos clave ignorados.

    Retorna una tupla: (atributos_validos, atributos_clave_ignorados).
    """
    valid: list[dict[str, Any] | str] = []
    ignored: list[dict[str, Any] | str] = []

    for attr in attributes:
        attr_name = attr["name"] if isinstance(attr, dict) else str(attr)
        if is_any_key_name(attr_name, class_name):
            ignored.append(attr)
        else:
            valid.append(attr)

    return valid, ignored
