from enum import StrEnum


class AgentActivityState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
