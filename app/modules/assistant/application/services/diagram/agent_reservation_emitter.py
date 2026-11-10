"""Emisor de reservas y liberaciones de componentes de diagrama correlacionadas con el mensaje."""

from __future__ import annotations

from typing import Callable
from uuid import UUID

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentComponentReservationEvent,
    AgentComponentReservationPublisher,
    AgentReservationActivityType,
    AgentReservationComponentType,
)


class AgentReservationEmitter:
    """Emite eventos de reserva para componentes de diagrama (clase, relación) con secuencia monotónica."""

    def __init__(
        self,
        publisher: AgentComponentReservationPublisher | None = None,
        *,
        project_id: UUID | None = None,
        message_id: UUID | None = None,
        sequence_factory: Callable[[], int] | None = None,
    ) -> None:
        self._publisher = publisher
        self._project_id = project_id
        self._message_id = message_id
        self._seq = 0
        self._sequence_factory = sequence_factory

    @property
    def publisher(self) -> AgentComponentReservationPublisher | None:
        return self._publisher

    @property
    def project_id(self) -> UUID | None:
        return self._project_id

    @property
    def message_id(self) -> UUID | None:
        return self._message_id

    def _next_sequence(self) -> int:
        if self._sequence_factory is not None:
            return self._sequence_factory()
        self._seq += 1
        return self._seq

    async def reserve_class(
        self,
        class_id: UUID,
        activity_type: AgentReservationActivityType = AgentReservationActivityType.QUERY,
        attribute_id: UUID | None = None,
    ) -> None:
        if self._publisher is None or self._project_id is None or self._message_id is None:
            return
        seq = self._next_sequence()
        event = AgentComponentReservationEvent(
            project_id=self._project_id,
            message_id=self._message_id,
            sequence=seq,
            component_type=AgentReservationComponentType.CLASS,
            component_id=class_id,
            activity_type=activity_type,
            attribute_id=attribute_id,
        )
        await self._publisher.publish_reservation(event)

    async def reserve_relation(
        self,
        relation_id: UUID,
        activity_type: AgentReservationActivityType = AgentReservationActivityType.QUERY,
        *,
        source_class_id: UUID | None = None,
        target_class_id: UUID | None = None,
        bridge_class_id: UUID | None = None,
    ) -> None:
        if self._publisher is None or self._project_id is None or self._message_id is None:
            return
        seq = self._next_sequence()
        event = AgentComponentReservationEvent(
            project_id=self._project_id,
            message_id=self._message_id,
            sequence=seq,
            component_type=AgentReservationComponentType.RELATION,
            component_id=relation_id,
            activity_type=activity_type,
        )
        await self._publisher.publish_reservation(event)

        if source_class_id is not None:
            await self.reserve_class(source_class_id, activity_type)
        if target_class_id is not None:
            await self.reserve_class(target_class_id, activity_type)
        if bridge_class_id is not None:
            await self.reserve_class(bridge_class_id, activity_type)

    async def release_reservations(self) -> None:
        if self._publisher is None or self._project_id is None or self._message_id is None:
            return
        await self._publisher.publish_release(self._project_id, self._message_id)
