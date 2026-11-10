from __future__ import annotations

from enum import StrEnum
from typing import Any


class DiagramRelationType(StrEnum):
    ASSOCIATION = "ASSOCIATION"
    AGGREGATION = "AGGREGATION"
    COMPOSITION = "COMPOSITION"
    GENERALIZATION = "GENERALIZATION"
    REALIZATION = "REALIZATION"
    DEPENDENCY = "DEPENDENCY"

    @classmethod
    def _missing_(cls, value: object) -> DiagramRelationType | None:
        if isinstance(value, str):
            clean = value.strip().upper()
            for member in cls:
                if member.value == clean:
                    return member
            lower = clean.lower()
            if lower in ("herencia", "generalizacion", "generalización", "inheritance"):
                return cls.GENERALIZATION
            if lower in ("composicion", "composición", "composition"):
                return cls.COMPOSITION
            if lower in ("agregacion", "agregación", "aggregation"):
                return cls.AGGREGATION
            if lower in ("asociacion", "asociación", "association"):
                return cls.ASSOCIATION
            if lower in ("realizacion", "realización", "realization"):
                return cls.REALIZATION
            if lower in ("dependencia", "dependency"):
                return cls.DEPENDENCY
            return cls.ASSOCIATION
        return None

    @classmethod
    def from_raw(cls, value: Any) -> DiagramRelationType:
        if isinstance(value, cls):
            return value
        if not value or not isinstance(value, str):
            return cls.ASSOCIATION
        return cls(value)

