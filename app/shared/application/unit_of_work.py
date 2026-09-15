"""Puertos de unidad de trabajo usados por casos de uso transaccionales."""

from typing import Protocol

from app.shared.domain.domain_event import DomainEvent


class UnitOfWorkPort(Protocol):
    """Contrato mínimo que permite agrupar casos de uso sin exponer una sesión ORM."""

    def publish_event(self, event: DomainEvent) -> None:
        ...

    def flush(self) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
