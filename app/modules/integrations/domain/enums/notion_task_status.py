from enum import Enum


class NotionTaskStatus(str, Enum):
    """Estados canónicos permitidos para tareas de Notion."""

    PENDING = "Pendiente"
    IN_PROGRESS = "En progreso"
    DONE = "Done"

    @classmethod
    def from_raw(cls, value: str | None) -> "NotionTaskStatus":
        if not value or not isinstance(value, str):
            return cls.PENDING
        clean = value.strip().casefold()
        if clean in {
            "done",
            "hecho",
            "hecha",
            "terminado",
            "terminada",
            "completado",
            "completada",
            "listo",
            "lista",
            "completed",
        }:
            return cls.DONE
        if clean in {
            "en progreso",
            "in progress",
            "in_progress",
            "progreso",
            "en proceso",
            "doing",
        }:
            return cls.IN_PROGRESS
        return cls.PENDING
