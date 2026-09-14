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
    from app.modules.diagram.domain.events.diagram_events import (
        DiagramAttributeCreatedEvent,
        DiagramAttributeDeletedEvent,
        DiagramAttributeRepositionedEvent,
        DiagramAttributeUpdatedEvent,
        DiagramClassCreatedEvent,
        DiagramClassDeletedEvent,
        DiagramClassMovedEvent,
        DiagramClassRenamedEvent,
        DiagramRelationCreatedEvent,
        DiagramRelationDeletedEvent,
        DiagramRelationRenamedEvent,
    )
    from app.modules.diagram.infrastructure.realtime.broadcast_handler import (
        websocket_broadcast_handler,
    )

    for event_type in (
        DiagramClassCreatedEvent,
        DiagramClassMovedEvent,
        DiagramClassRenamedEvent,
        DiagramClassDeletedEvent,
        DiagramAttributeCreatedEvent,
        DiagramAttributeUpdatedEvent,
        DiagramAttributeRepositionedEvent,
        DiagramAttributeDeletedEvent,
        DiagramRelationCreatedEvent,
        DiagramRelationRenamedEvent,
        DiagramRelationDeletedEvent,
    ):
        event_bus.subscribe(event_type, websocket_broadcast_handler.handle)
