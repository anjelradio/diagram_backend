"""
app/shared/domain/aggregate_root.py

Clase base para todos los Aggregates del sistema.
"""

from app.shared.domain.domain_event import DomainEvent


class AggregateRoot:
    """
    Clase base para Aggregates del dominio que emiten Domain Events.

    Gestiona internamente una lista de eventos que se acumulan a medida
    que el aggregate ejecuta métodos de negocio o métodos de fábrica (`@classmethod`).
    El UnitOfWork los recoge con ``pull_events()`` después de un commit exitoso
    para despacharlos al Event Bus.

    Arquitectura: ¿Cuándo usar AggregateRoot vs Entidad normal?
    ----------------------------------------------------------
    - En DDD modular, los Domain Events se usan principalmente para
      comunicar hechos a OTROS módulos o para efectos secundarios desacoplados
      (emails, notificaciones, auditorías).
    - Si un módulo o acción es autosuficiente y NO necesita notificar a nadie,
      la entidad debe ser una CLASE NORMAL de Python (o dataclass) y NO heredar
      de AggregateRoot.
    - Gracias a la inicialización perezosa, las subclases de AggregateRoot
      pueden usar constructores propios y fábricas `@classmethod` sin requerir
      obligatoriamente llamar a `super().__init__()`.

    Ejemplo
    -------
    ::

        class Book(AggregateRoot):
            def __init__(self, id: UUID, title: str, is_active: bool = True) -> None:
                self.id = id
                self.title = title
                self.is_active = is_active

            @classmethod
            def add_to_catalog(cls, *, title: str) -> "Book":
                book = cls(id=uuid4(), title=title, is_active=True)
                book._record_event(BookAddedToCatalog(book_id=book.id, title=title))
                return book
    """

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _get_event_store(self) -> list[DomainEvent]:
        """Inicializa de forma perezosa la lista de eventos si no existe."""
        if not hasattr(self, "_domain_events") or self._domain_events is None:
            self._domain_events = []
        return self._domain_events

    def _record_event(self, event: DomainEvent) -> None:
        """
        Registra un evento de dominio en la lista interna.

        Solo debe ser llamado por el propio aggregate dentro de sus
        métodos de comportamiento o fábricas (`@classmethod`), nunca desde fuera.
        """
        self._get_event_store().append(event)

    def pull_events(self) -> list[DomainEvent]:
        """
        Retorna todos los eventos acumulados y limpia la lista interna.
        Solo debe ser llamado por el UnitOfWork durante el commit.
        """
        events = list(self._get_event_store())
        self._get_event_store().clear()
        return events

    def discard_events(self) -> None:
        """Descarta eventos pendientes cuando el Unit of Work hace rollback."""
        self._get_event_store().clear()

    @property
    def has_events(self) -> bool:
        """True si hay eventos acumulados pendientes de despacho."""
        return len(self._get_event_store()) > 0
