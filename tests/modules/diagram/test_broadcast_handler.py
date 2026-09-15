import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.modules.diagram.domain.events.diagram_events import DiagramMutationEvent
from app.modules.diagram.infrastructure.realtime.broadcast_handler import (
    WebSocketBroadcastEventHandler,
    configure_broadcast_loop,
)


def test_broadcast_handler_without_loop() -> None:
    handler = WebSocketBroadcastEventHandler()
    event = DiagramMutationEvent(
        project_id=uuid4(),
        sender_id="sender_1",
        operation_type="MOVE_CLASS",
        data={"class_id": str(uuid4())},
    )
    # Should not raise exception
    handler.handle(event)


def test_broadcast_handler_with_loop() -> None:
    async def _run() -> None:
        loop = asyncio.get_running_loop()
        configure_broadcast_loop(loop)

        handler = WebSocketBroadcastEventHandler()
        project_id = uuid4()
        event = DiagramMutationEvent(
            project_id=project_id,
            sender_id="sender_1",
            operation_type="MOVE_CLASS",
            data={"class_id": str(uuid4())},
        )

        with patch("app.modules.diagram.infrastructure.realtime.broadcast_handler.connection_manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
            handler.handle(event)
            # Yield to let scheduled coroutine run
            await asyncio.sleep(0.05)

            mock_broadcast.assert_awaited_once_with(
                project_id,
                {
                    "type": "diagram_mutation",
                    "operation_type": "MOVE_CLASS",
                    "data": event.data,
                    "sender_id": "sender_1",
                },
                exclude_user_id="sender_1",
            )

    asyncio.run(_run())
