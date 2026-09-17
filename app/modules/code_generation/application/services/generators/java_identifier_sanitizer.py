import re

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
    words = re.split(r"[\s_-]+", raw)
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
