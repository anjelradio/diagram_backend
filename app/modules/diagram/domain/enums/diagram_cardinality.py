from enum import StrEnum


class DiagramCardinality(StrEnum):
    ZERO_OR_ONE = "0..1"
    EXACTLY_ONE = "1"
    ZERO_OR_MORE = "0..*"
    ONE_OR_MORE = "1..*"

    @classmethod
    def _missing_(cls, value: object) -> "DiagramCardinality | None":
        # El frontend históricamente etiqueta EXACTLY_ONE como 1..1; canonicalizar
        # en el límite HTTP evita que esa notación rompa el enum o la persistencia.
        if value == "1..1":
            return cls.EXACTLY_ONE
        return None
