from enum import Enum


class AgentMessageStatus(str, Enum):
    """Estados persistibles de un mensaje del asistente."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

