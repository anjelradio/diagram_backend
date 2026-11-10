from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    to_snake_case,
)
from app.modules.integrations.domain.exceptions import (
    NeonDiagramValidationException,
)


@dataclass(frozen=True)
class PostgresValidationResult:
    """Resultado determinista de la validación pre-SQL del diagrama."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    table_names_by_class_id: dict[UUID, str] = field(default_factory=dict)
    column_names_by_attribute_id: dict[UUID, str] = field(default_factory=dict)


class PostgresDiagramValidator:
    """Valida un snapshot del diagrama UML antes de desplegar o migrar en Neon PostgreSQL.

    Garantiza:
    1. Diagrama no vacío (al menos 1 clase).
    2. Sin clases duplicadas (nombre de clase o tabla SQL snake_case colisionante).
    3. Sin atributos duplicados dentro de una misma clase (nombre o columna SQL colisionante).
    """

    @classmethod
    def validate(
        cls,
        classes: list[Any],
        relations: list[Any] | None = None,
        attributes_by_class: dict[UUID, list[Any]] | None = None,
        *,
        raise_on_error: bool = True,
    ) -> PostgresValidationResult:
        errors: list[str] = []
        table_names_by_class_id: dict[UUID, str] = {}
        column_names_by_attr_id: dict[UUID, str] = {}

        # 1. Regla: Diagrama no vacío
        if not classes:
            errors.append("El diagrama está vacío. Debes tener al menos una clase antes de desplegar en Neon.")
            if raise_on_error:
                raise NeonDiagramValidationException("; ".join(errors))
            return PostgresValidationResult(is_valid=False, errors=errors)

        # 2. Regla: Unicidad de clases y nombres de tabla
        seen_exact_class_names: dict[str, str] = {}
        seen_table_names: dict[str, str] = {}

        for c in classes:
            c_id = getattr(c, "id", None) or (UUID(c["id"]) if isinstance(c.get("id"), str) else c["id"])
            c_name = getattr(c, "name", None) or c.get("name", "")
            clean_name = str(c_name).strip()
            table_name = to_snake_case(clean_name)

            table_names_by_class_id[c_id] = table_name

            # Chequeo por nombre exacto case-insensitive
            normalized_class_name = clean_name.casefold()
            if normalized_class_name in seen_exact_class_names:
                errors.append(
                    f"Conflicto de clases duplicadas: '{clean_name}' colisiona con '{seen_exact_class_names[normalized_class_name]}'."
                )
            else:
                seen_exact_class_names[normalized_class_name] = clean_name

            # Chequeo por identificador de tabla SQL generado
            if table_name in seen_table_names:
                errors.append(
                    f"Conflicto de tabla SQL duplicada: Las clases '{clean_name}' y '{seen_table_names[table_name]}' "
                    f"producen el mismo nombre de tabla en PostgreSQL ('{table_name}')."
                )
            else:
                seen_table_names[table_name] = clean_name

        # 3. Regla: Unicidad de atributos dentro de cada clase
        attrs_map = attributes_by_class or {}
        for c in classes:
            c_id = getattr(c, "id", None) or (UUID(c["id"]) if isinstance(c.get("id"), str) else c["id"])
            c_name = getattr(c, "name", None) or c.get("name", "")

            # Obtener atributos de la clase
            attrs = attrs_map.get(c_id)
            if attrs is None:
                attrs = getattr(c, "attributes", None) or (c.get("attributes") if isinstance(c, dict) else [])
            attrs = attrs or []

            seen_exact_attr_names: dict[str, str] = {}
            seen_column_names: dict[str, str] = {}

            for a in attrs:
                a_id = getattr(a, "id", None) or (UUID(a["id"]) if isinstance(a.get("id"), str) else a["id"])
                a_name = getattr(a, "name", None) or a.get("name", "")
                clean_attr_name = str(a_name).strip()
                col_name = to_snake_case(clean_attr_name)

                column_names_by_attr_id[a_id] = col_name

                normalized_attr_name = clean_attr_name.casefold()
                if normalized_attr_name in seen_exact_attr_names:
                    errors.append(
                        f"En la clase '{c_name}', el atributo '{clean_attr_name}' está duplicado."
                    )
                else:
                    seen_exact_attr_names[normalized_attr_name] = clean_attr_name

                if col_name in seen_column_names:
                    errors.append(
                        f"En la clase '{c_name}', los atributos '{clean_attr_name}' y '{seen_column_names[col_name]}' "
                        f"producen el mismo nombre de columna SQL ('{col_name}')."
                    )
                else:
                    seen_column_names[col_name] = clean_attr_name

        is_valid = len(errors) == 0
        if not is_valid and raise_on_error:
            raise NeonDiagramValidationException("; ".join(errors))

        return PostgresValidationResult(
            is_valid=is_valid,
            errors=errors,
            table_names_by_class_id=table_names_by_class_id,
            column_names_by_attribute_id=column_names_by_attr_id,
        )
