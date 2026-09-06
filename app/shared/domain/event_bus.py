"""
app/shared/domain/event_bus.py

Interfaz abstracta del Event Bus de dominio (sin prefijo I).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeAlias

from app.shared.domain.domain_event import DomainEvent

EventHandler: TypeAlias = Callable[[DomainEvent], None]


class EventBus(ABC):
    """
    Interfaz del bus de eventos de dominio (sin prefijo I).

    Define el contrato para publicar y suscribirse a eventos.
    El bus actual se usa para efectos internos post-commit. No ofrece
    persistencia, reintentos ni comunicación entre procesos.
    """

    @abstractmethod
    def publish(self, event: DomainEvent) -> None:
        """Publica un evento para que todos los handlers suscritos lo procesen."""
        ...

    @abstractmethod
    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
    ) -> None:
        """Suscribe un callable como handler de un tipo de evento."""
        ...


# Alias de compatibilidad
IEventBus = EventBus
