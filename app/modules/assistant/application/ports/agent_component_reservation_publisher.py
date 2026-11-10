"""Puerto para emitir reservas y liberaciones de componentes de diagrama por el agente."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID


class AgentReservationComponentType(str, Enum):
    CLASS = "class"
    RELATION = "relation"


class AgentReservationActivityType(str, Enum):
    QUERY = "query"
    EDIT = "edit"


@dataclass(frozen=True, slots=True)
class AgentComponentReservationEvent:
    """Evento que describe la reserva de un componente sin exponer prompt ni razonamiento."""

    project_id: UUID
    message_id: UUID
    sequence: int
    component_type: AgentReservationComponentType
    component_id: UUID
    activity_type: AgentReservationActivityType
    attribute_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("La secuencia de reserva debe ser positiva.")


class AgentComponentReservationPublisher(Protocol):
    """Publica reservas y liberaciones de componentes del agente."""

    async def publish_reservation(self, event: AgentComponentReservationEvent) -> None:
        """La pérdida de realtime nunca debe revertir el trabajo del agente."""
        ...

    async def publish_release(self, project_id: UUID, message_id: UUID) -> None:
        """Libera todas las reservas de un mensaje terminal."""
        ...

    def publish_release_sync(self, project_id: UUID, message_id: UUID) -> None:
        """Libera todas las reservas de un mensaje terminal de forma sincrónica."""
        ...

