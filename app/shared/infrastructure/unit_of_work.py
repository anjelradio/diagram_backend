import logging

from sqlmodel import Session

from app.shared.domain.aggregate_root import AggregateRoot
from app.shared.domain.domain_event import DomainEvent
from app.shared.domain.event_bus import EventBus

logger = logging.getLogger(__name__)


class SqlModelUnitOfWork:
    """
    Unit of Work base para SQLModel (implementa UnitOfWork port).

    Coordina dos responsabilidades críticas en cada operación de escritura:

    1. **Persistencia transaccional**: agrupa todas las operaciones de BD
       en una única transacción atómica via ``session.commit()``.

    2. **Despacho de Domain Events**: después del commit exitoso, recoge
       todos los eventos acumulados en los aggregates trackeados y los
       publica al Event Bus. Si una entidad guardada NO es un AggregateRoot,
       simplemente se persiste en la BD sin emitir eventos.

    Soporte Context Manager:
    -----------------------
    ::

        with uow:
            uow.books.save(book)
            uow.commit()

    Herencia en módulos
    -------------------
    Cada módulo crea su propio UoW en su capa infrastructure/persistence/::

        class CatalogUnitOfWork(SqlModelUnitOfWork):
            def __init__(self, session: Session, event_bus: EventBus):
                super().__init__(session, event_bus)
                self.books = SQLModelBookRepository(session, self.track)
    """

    def __init__(self, session: Session, event_bus: EventBus) -> None:
        self.session = session
        self._event_bus = event_bus
        self._tracked_aggregates: list[AggregateRoot] = []
        self._pending_events: list[DomainEvent] = []

    def publish_event(self, event: DomainEvent) -> None:
        """Programa un evento para publicarlo únicamente tras un commit exitoso."""
        self._pending_events.append(event)

    def __enter__(self) -> "SqlModelUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if exc_type is not None:
            self.rollback()

    def track(self, entity: object) -> None:
        """
        Registra un aggregate para recoger sus eventos durante el commit.

        Si la entidad guardada no es un AggregateRoot (por ejemplo, una entidad
        simple que no emite eventos de dominio), se ignora de forma segura.
        """
        if isinstance(entity, AggregateRoot):
            if not any(tracked is entity for tracked in self._tracked_aggregates):
                self._tracked_aggregates.append(entity)

    def commit(self) -> None:
        """
        Persiste los cambios en BD y despacha los Domain Events acumulados.

        Secuencia garantizada:
        1. ``session.commit()`` confirma los datos en base de datos.
        2. ``pull_events()`` recoge y limpia eventos de cada aggregate.
        3. ``event_bus.publish()`` despacha cada evento best effort.
        4. La lista de aggregates trackeados se limpia siempre.
        """
        try:
            self.session.commit()
        except Exception:
            self.rollback()
            raise

        logger.debug("UnitOfWork — commit exitoso")

        events: list[DomainEvent] = list(self._pending_events)
        try:
            for aggregate in self._tracked_aggregates:
                events.extend(aggregate.pull_events())

            for event in events:
                try:
                    self._event_bus.publish(event)
                except Exception:
                    logger.exception(
                        "UnitOfWork - error inesperado al publicar '%s' (event_id=%s)",
                        type(event).__name__,
                        event.event_id,
                    )
        finally:
            self._tracked_aggregates.clear()
            self._pending_events.clear()

    def rollback(self) -> None:
        """
        Revierte los cambios pendientes y limpia el estado del UoW.
        """
        self.session.rollback()
        for aggregate in self._tracked_aggregates:
            aggregate.discard_events()
        self._tracked_aggregates.clear()
        self._pending_events.clear()
        logger.debug("UnitOfWork — rollback ejecutado")
