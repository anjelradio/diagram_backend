from __future__ import annotations

from enum import StrEnum
from typing import Any


class DiagramAttributeDataType(StrEnum):
    UUID = "UUID"
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"

    @classmethod
    def _missing_(cls, value: object) -> DiagramAttributeDataType | None:
        if isinstance(value, str):
            clean = value.strip().upper()
            for member in cls:
                if member.value == clean:
                    return member
            lower = clean.lower()
            if lower in ("str", "string", "varchar", "char", "text"):
                return cls.TEXT
            if lower in ("int", "integer", "bigint", "smallint", "number", "long", "short", "serial"):
                return cls.INTEGER
            if lower in ("float", "double", "decimal", "numeric", "real"):
                return cls.DECIMAL
            if lower in ("bool", "boolean"):
                return cls.BOOLEAN
            if lower in ("date",):
                return cls.DATE
            if lower in ("datetime", "timestamp", "time", "localdatetime", "local_date_time"):
                return cls.TIMESTAMP
            if lower in ("uuid", "guid"):
                return cls.UUID
            return None
        return None

    @classmethod
    def from_raw(cls, value: Any) -> DiagramAttributeDataType:
        """Convierte flexiblemente cualquier cadena o tipo estándar a DiagramAttributeDataType."""
        if isinstance(value, cls):
            return value
        if not value or not isinstance(value, str):
            return cls.TEXT
        return cls(value)

