from enum import Enum


class DiagramAuditAction(str, Enum):
    """Acción canónica de mutación registrada en la bitácora."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
