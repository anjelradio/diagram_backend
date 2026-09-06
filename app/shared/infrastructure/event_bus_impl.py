import logging
from collections import defaultdict
from threading import RLock

from app.shared.domain.domain_event import DomainEvent
from app.shared.domain.event_bus import EventBus, EventHandler

logger = logging.getLogger(__name__)


class InMemoryEventBus(EventBus):
    """
    Bus de eventos sincrónico en memoria.

    Los handlers suscritos se ejecutan de forma sincrónica y secuencial
    en el mismo hilo, inmediatamente después de que el Unit of Work
    realiza el commit exitoso.

    Esta implementación es adecuada para efectos secundarios internos y
    no críticos de un monolito modular.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = (
            defaultdict(list)
        )
        self._lock = RLock()

    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
    ) -> None:
        handler_name = self._handler_name(handler)

        with self._lock:
            handlers = self._handlers[event_type]
            if handler in handlers:
                logger.debug(
                    "EventBus - handler '%s' ya estaba suscrito a '%s'",
                    handler_name,
                    event_type.__name__,
                )
                return

            handlers.append(handler)

        logger.info(
            "EventBus - handler '%s' suscrito a '%s'",
            handler_name,
            event_type.__name__,
        )

    def publish(self, event: DomainEvent) -> None:
        event_type = type(event)
        with self._lock:
            handlers = tuple(self._handlers.get(event_type, ()))

        if not handlers:
            logger.debug(
                "EventBus - '%s' publicado sin suscriptores (event_id=%s)",
                event_type.__name__,
                event.event_id,
            )
            return

        for handler in handlers:
            try:
                logger.debug(
                    "EventBus - ejecutando handler '%s' para '%s' (event_id=%s)",
                    self._handler_name(handler),
                    event_type.__name__,
                    event.event_id,
                )
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus - error en handler '%s' procesando '%s' (event_id=%s)",
                    self._handler_name(handler),
                    event_type.__name__,
                    event.event_id,
                )

    @staticmethod
    def _handler_name(handler: EventHandler) -> str:
        return getattr(handler, "__qualname__", type(handler).__qualname__)
