"""
app/core/dependencies.py

Dependencias reutilizables de FastAPI.

Este archivo es el único punto de importación para los módulos
que necesiten acceder a la BD, al Event Bus o verificar autenticación.

Uso en un router:
----------------
::

    from app.core.dependencies import DBSession, EventBusDep, CurrentUser, Admin

    @router.get("/items")
    def list_items(db: DBSession, user: CurrentUser):
        ...
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.core.database import get_session
from app.core.security.auth import Admin, CurrentUser
from app.shared.domain.event_bus import EventBus
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork

# ── Base de datos ─────────────────────────────────────────────────────────────

DBSession = Annotated[Session, Depends(get_session)]
"""Sesión de BD inyectada por request. Úsala en endpoints o dependencias de módulo."""

# ── Event Bus (singleton) ─────────────────────────────────────────────────────

_event_bus = InMemoryEventBus()
"""
Instancia singleton del Event Bus.

No importar ni usar directamente desde los módulos.
Usar ``EventBusDep`` en dependencias de módulo, o ``get_event_bus()``
cuando se necesite la instancia para registrar suscripciones en startup.
"""


def get_event_bus() -> EventBus:
    """
    Retorna la instancia singleton del Event Bus.

    FastAPI la inyecta automáticamente via ``EventBusDep``.
    También se usa en ``main.py`` para pasar el bus a
    ``configure_event_subscriptions()`` durante el lifespan.
    """
    return _event_bus


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
"""Event Bus inyectado por request. Úsalo en dependencias de módulo (UoW factories)."""

# ── Unit of Work Genérico ─────────────────────────────────────────────────────

def get_uow(
    session: Session = Depends(get_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> Iterator[SqlModelUnitOfWork]:
    """
    Entrega un Unit of Work genérico listo para usar en endpoints de comandos.
    Garantiza el rollback automático si ocurre una excepción no manejada.
    """
    with SqlModelUnitOfWork(session, event_bus) as uow:
        yield uow


UoWDep = Annotated[SqlModelUnitOfWork, Depends(get_uow)]
"""Unit of Work Genérico inyectado por request."""

# ── Re-exports ────────────────────────────────────────────────────────────────

__all__ = [
    # DB
    "DBSession",
    # Event Bus
    "EventBusDep",
    "get_event_bus",
    # Identities
    "CurrentUser",
    "Admin",
    # UoW
    "UoWDep",
]
