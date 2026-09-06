"""
app/shared/domain

Exportación de bloques de construcción centrales de Domain-Driven Design (DDD).
"""

from app.shared.domain.aggregate_root import AggregateRoot
from app.shared.domain.domain_event import DomainEvent
from app.shared.domain.event_bus import EventBus, EventHandler, IEventBus
from app.shared.domain.exceptions import (
    ConflictException,
    DomainException,
    NotFoundException,
    ValidationException,
)
from app.shared.domain.value_object import ValueObject

__all__ = [
    # Building blocks
    "AggregateRoot",
    "DomainEvent",
    "EventBus",
    "IEventBus",
    "EventHandler",
    "ValueObject",
    # Exceptions
    "DomainException",
    "NotFoundException",
    "ValidationException",
    "ConflictException",
]
