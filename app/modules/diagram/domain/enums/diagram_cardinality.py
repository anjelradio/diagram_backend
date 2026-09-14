from enum import StrEnum


class DiagramCardinality(StrEnum):
    ZERO_OR_ONE = "0..1"
    EXACTLY_ONE = "1"
    ZERO_OR_MORE = "0..*"
    ONE_OR_MORE = "1..*"
