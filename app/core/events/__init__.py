"""
app/core/events

Configuración y suscripciones del bus de eventos interno.
"""

from app.core.events.subscriptions import configure_event_subscriptions

__all__ = ["configure_event_subscriptions"]
