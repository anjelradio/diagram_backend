"""Puerto y contrato cerrado para el estado efímero de una ejecución."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID


class AgentActivityCode(str, Enum):
    PREPARING_CONTEXT = "preparing_context"
    ANALYZING_PROMPT = "analyzing_prompt"
    PLANNING = "planning"
    ANALYZING_IMAGE = "analyzing_image"
    READING_DIAGRAM = "reading_diagram"
    READING_CLASSES = "reading_classes"
    READING_ATTRIBUTES = "reading_attributes"
    READING_RELATIONS = "reading_relations"
    CREATING_CLASS = "creating_class"
    EDITING_CLASS = "editing_class"
    DELETING_CLASS = "deleting_class"
    CREATING_ATTRIBUTE = "creating_attribute"
    EDITING_ATTRIBUTE = "editing_attribute"
    DELETING_ATTRIBUTE = "deleting_attribute"
    CREATING_RELATION = "creating_relation"
    EDITING_RELATION = "editing_relation"
    DELETING_RELATION = "deleting_relation"
    RECALLING_CONVERSATION = "recalling_conversation"
    FINALIZING = "finalizing"


class AgentActivityType(str, Enum):
    QUERY = "query"
    EDIT = "edit"
    ANALYSIS = "analysis"
    PLANNING = "planning"


def get_activity_type(code: AgentActivityCode) -> AgentActivityType:
    if code in (
        AgentActivityCode.READING_DIAGRAM,
        AgentActivityCode.READING_CLASSES,
        AgentActivityCode.READING_ATTRIBUTES,
        AgentActivityCode.READING_RELATIONS,
        AgentActivityCode.RECALLING_CONVERSATION,
    ):
        return AgentActivityType.QUERY
    if code in (
        AgentActivityCode.CREATING_CLASS,
        AgentActivityCode.EDITING_CLASS,
        AgentActivityCode.DELETING_CLASS,
        AgentActivityCode.CREATING_ATTRIBUTE,
        AgentActivityCode.EDITING_ATTRIBUTE,
        AgentActivityCode.DELETING_ATTRIBUTE,
        AgentActivityCode.CREATING_RELATION,
        AgentActivityCode.EDITING_RELATION,
        AgentActivityCode.DELETING_RELATION,
    ):
        return AgentActivityType.EDIT
    if code == AgentActivityCode.PLANNING:
        return AgentActivityType.PLANNING
    return AgentActivityType.ANALYSIS


@dataclass(frozen=True, slots=True)
class AgentActivity:
    """Descripción pública de un paso real, sin contenido del prompt ni de las tools."""

    project_id: UUID
    message_id: UUID
    attempt_id: UUID
    sequence: int
    code: AgentActivityCode
    occurred_at: datetime
    activity_type: AgentActivityType | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("La secuencia de actividad debe ser positiva.")
        if self.activity_type is None:
            object.__setattr__(self, "activity_type", get_activity_type(self.code))


class AgentActivityPublisher(Protocol):
    """Publica una fase efímera en la sala autorizada del proyecto."""

    async def publish_activity(self, activity: AgentActivity) -> None:
        """La pérdida de realtime nunca debe revertir el trabajo del agente."""
        ...
