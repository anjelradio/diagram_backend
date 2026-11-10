from enum import Enum


class DiagramAuditEntityType(str, Enum):
    """Categoría de la entidad afectada por una operación de diagrama."""

    CLASS = "CLASS"
    ATTRIBUTE = "ATTRIBUTE"
    RELATION = "RELATION"
