from enum import Enum


class NotionTaskPriority(str, Enum):
    """Niveles de prioridad permitidos para tareas de Notion."""

    HIGH = "Alta"
    MEDIUM = "Media"
    LOW = "Baja"

    @classmethod
    def from_raw(cls, value: str | None) -> "NotionTaskPriority":
        if not value or not isinstance(value, str):
            return cls.MEDIUM
        clean = value.strip().casefold()
        if clean in {"alta", "high", "urgente", "critica", "crítica"}:
            return cls.HIGH
        if clean in {"baja", "low", "menor"}:
            return cls.LOW
        return cls.MEDIUM
