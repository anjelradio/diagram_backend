"""
app/core/events/subscriptions.py

Registro centralizado de todos los handlers de eventos del sistema.

Este módulo es el único lugar donde se configuran las suscripciones
entre eventos y sus handlers. Se invoca una sola vez durante el
startup de la aplicación (lifespan en main.py).

Convención
----------
Cada módulo agrega sus suscripciones en la sección correspondiente.
Los imports de los handlers se hacen dentro de la función para evitar
importaciones circulares entre módulos.
"""

from app.shared.domain.event_bus import EventBus


def configure_event_subscriptions(event_bus: EventBus) -> None:
    """
    Registra todos los handlers de eventos del sistema en el Event Bus.

    Se llama una sola vez durante el startup de la aplicación.
    Agregar suscripciones por módulo en las secciones indicadas.
    """
    # ── Módulo A ──────────────────────────────────────────────────────────────
    # from app.modules.orders.domain.events import OrderPlaced
    # from app.modules.notifications.application.handlers.on_order_placed import OnOrderPlacedHandler
    # event_bus.subscribe(OrderPlaced, handler.handle)
    pass
