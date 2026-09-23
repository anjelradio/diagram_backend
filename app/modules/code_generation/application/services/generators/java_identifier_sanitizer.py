from dataclasses import dataclass
import re

from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
)

JAVA_RESERVED_WORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "record", "var", "yield",
    "order", "group", "user", "table"
}


def sanitize_raw_text(text: str) -> str:
    """Elimina caracteres inválidos preservando letras, dígitos y guiones."""
    if not text:
        return "Item"
    # Reemplazar caracteres especiales por espacios
    cleaned = re.sub(r"[^\w\s-]", "", text.strip())
    return cleaned if cleaned else "Item"


def to_pascal_case(text: str) -> str:
    """Convierte texto a PascalCase válido para clases Java (ej. 'producto_detalle' -> 'ProductoDetalle')."""
    raw = sanitize_raw_text(text)
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1 \2", raw)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s1)
    words = [w for w in re.split(r"[\s_-]+", s2) if w]
    pascal = "".join(w.capitalize() for w in words if w)
    if not pascal:
        pascal = "Entity"
    if pascal[0].isdigit():
        pascal = f"Clase{pascal}"
    return pascal


def to_camel_case(text: str) -> str:
    """Convierte texto a camelCase válido para campos y métodos Java (ej. 'fecha_creacion' -> 'fechaCreacion')."""
    pascal = to_pascal_case(text)
    camel = pascal[0].lower() + pascal[1:] if len(pascal) > 1 else pascal.lower()
    if camel in JAVA_RESERVED_WORDS:
        camel = f"_{camel}"
    return camel


def to_snake_case(text: str) -> str:
    """Convierte texto a snake_case para nombres de tabla y columna en SQL."""
    raw = sanitize_raw_text(text)
    # Convertir CamelCase a snake_case
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", raw)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    snake = re.sub(r"[-\s]+", "_", s2)
    snake = re.sub(r"_+", "_", snake).strip("_")
    if snake in {"order", "user", "group", "table", "select", "check"}:
        snake = f"{snake}s"
    return snake if snake else "records"


def to_kebab_case(text: str) -> str:
    """Convierte texto a kebab-case para rutas de API REST (ej. 'Producto' -> 'productos')."""
    snake = to_snake_case(text)
    kebab = snake.replace("_", "-")
    # Pluralización básica
    if kebab.endswith("s") or kebab.endswith("x") or kebab.endswith("z"):
        return f"{kebab}es"
    if kebab.endswith("y") and len(kebab) > 1 and kebab[-2] not in "aeiou":
        return f"{kebab[:-1]}ies"
    return f"{kebab}s"


def map_data_type(data_type: str | None) -> tuple[str, str | None]:
    """Mapea tipos de datos del diagrama a tipos de datos Java y sus imports necesarios."""
    dt = (data_type or "").upper().strip()
    match dt:
        case "UUID":
            return "UUID", "java.util.UUID"
        case "TEXT" | "STRING" | "VARCHAR":
            return "String", None
        case "INTEGER" | "INT":
            return "Integer", None
        case "BIGINT" | "LONG":
            return "Long", None
        case "DECIMAL" | "FLOAT" | "DOUBLE":
            return "Double", None
        case "BOOLEAN" | "BOOL":
            return "Boolean", None
        case "DATE":
            return "LocalDate", "java.time.LocalDate"
        case "TIMESTAMP" | "DATETIME":
            return "LocalDateTime", "java.time.LocalDateTime"
        case _:
            return "String", None


def map_standard_type(data_type: str | None) -> str:
    """
    Mapea tipos de datos del diagrama a los tipos estandarizados en mayúsculas de Capabilities v2:
    UUID, STRING, INTEGER, DECIMAL, BOOLEAN, DATETIME.
    """
    dt = (data_type or "").upper().strip()
    match dt:
        case "UUID":
            return "UUID"
        case "TEXT" | "STRING" | "VARCHAR" | "CHAR":
            return "STRING"
        case "INTEGER" | "INT" | "BIGINT" | "LONG" | "SHORT" | "SERIAL":
            return "INTEGER"
        case "DECIMAL" | "FLOAT" | "DOUBLE" | "NUMERIC" | "REAL":
            return "DECIMAL"
        case "BOOLEAN" | "BOOL":
            return "BOOLEAN"
        case "DATE" | "TIMESTAMP" | "DATETIME" | "LOCALDATE" | "LOCALDATETIME":
            return "DATETIME"
        case _:
            return "STRING"


def map_sqlite_type(data_type: str | None) -> str:
    """
    Mapea tipos de datos del diagrama a afinidades de almacenamiento SQLite:
    TEXT, INTEGER, REAL.
    """
    dt = (data_type or "").upper().strip()
    match dt:
        case "UUID" | "TEXT" | "STRING" | "VARCHAR" | "CHAR" | "DATE" | "TIMESTAMP" | "DATETIME" | "LOCALDATE" | "LOCALDATETIME":
            return "TEXT"
        case "INTEGER" | "INT" | "BIGINT" | "LONG" | "SHORT" | "SERIAL" | "BOOLEAN" | "BOOL":
            return "INTEGER"
        case "DECIMAL" | "FLOAT" | "DOUBLE" | "NUMERIC" | "REAL":
            return "REAL"
        case _:
            return "TEXT"


@dataclass(frozen=True, slots=True)
class SanitizedAttribute:
    """Atributo sanitizado y desambiguado para generación Java sin colisiones."""

    original_name: str
    field_name: str
    method_suffix: str
    column_name: str
    java_type: str
    java_import: str | None
    is_primary_key: bool
    is_foreign_key: bool
    is_nullable: bool


def sanitize_class_attributes(
    attributes: list[DiagramAttributeSnapshotDto],
) -> list[SanitizedAttribute]:
    """
    Sanitiza y desambigua los atributos de una clase para evitar colisiones en Java y SQL.
    - Garantiza que la primary key 'id' esté en primera posición.
    - Renombra atributos secundarios llamados 'id' o 'Id' a 'externalId'.
    - Resuelve colisiones de nombres de campos y columnas repetidos.
    """
    seen_fields: set[str] = set()
    seen_cols: set[str] = set()
    sanitized: list[SanitizedAttribute] = []

    # 1. Primary key procesada en primer lugar
    pk_attr = next((a for a in attributes if a.is_primary_key), None)
    if pk_attr:
        jtype, jimport = map_data_type(pk_attr.data_type)
        sanitized.append(
            SanitizedAttribute(
                original_name=pk_attr.name,
                field_name="id",
                method_suffix="Id",
                column_name="id",
                java_type=jtype,
                java_import=jimport,
                is_primary_key=True,
                is_foreign_key=False,
                is_nullable=False,
            )
        )
        seen_fields.add("id")
        seen_cols.add("id")
    else:
        sanitized.append(
            SanitizedAttribute(
                original_name="id",
                field_name="id",
                method_suffix="Id",
                column_name="id",
                java_type="UUID",
                java_import="java.util.UUID",
                is_primary_key=True,
                is_foreign_key=False,
                is_nullable=False,
            )
        )
        seen_fields.add("id")
        seen_cols.add("id")

    # 2. Resto de atributos secundarios
    for attr in attributes:
        if attr.is_primary_key:
            continue

        base_field = to_camel_case(attr.name)
        # Si un atributo secundario colisiona con la primary key "id"
        if base_field.lower() == "id" or base_field == "id":
            base_field = "externalId"

        field_name = base_field
        counter = 2
        while field_name in seen_fields:
            field_name = f"{base_field}{counter}"
            counter += 1
        seen_fields.add(field_name)

        base_col = to_snake_case(attr.name)
        if base_col == "id":
            base_col = to_snake_case(field_name)
        col_name = base_col
        counter = 2
        while col_name in seen_cols:
            col_name = f"{base_col}_{counter}"
            counter += 1
        seen_cols.add(col_name)

        jtype, jimport = map_data_type(attr.data_type)
        suffix = (
            field_name[0].upper() + field_name[1:]
            if len(field_name) > 1
            else field_name.upper()
        )

        sanitized.append(
            SanitizedAttribute(
                original_name=attr.name,
                field_name=field_name,
                method_suffix=suffix,
                column_name=col_name,
                java_type=jtype,
                java_import=jimport,
                is_primary_key=False,
                is_foreign_key=attr.is_foreign_key,
                is_nullable=attr.is_nullable,
            )
        )

    return sanitized

