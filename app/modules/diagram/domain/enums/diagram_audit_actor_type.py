from enum import Enum


class DiagramAuditActorType(str, Enum):
    """Canal ejecutor de la operación sobre el proyecto."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
