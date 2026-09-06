"""
app/shared/domain/domain_event.py

Clase base para todos los eventos de dominio del sistema.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """
    Clase base para todos los eventos de dominio.

    Un evento de dominio representa un hecho significativo e inmutable
    que ya ocurrió dentro de un Bounded Context. Se nombra siempre en
    pasado: OrderPlaced, PaymentReceived, ProductDiscontinued.
    """

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
