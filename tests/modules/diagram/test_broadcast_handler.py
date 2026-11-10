import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.modules.diagram.domain.events.diagram_events import DiagramMutationEvent
from app.modules.diagram.infrastructure.realtime.broadcast_handler import (
    WebSocketBroadcastEventHandler,
    configure_broadcast_loop,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    ClientSession,
    ConnectionManager,
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


def test_agent_mutation_reaches_author_and_collaborators(monkeypatch) -> None:
    async def run():
        configure_broadcast_loop(asyncio.get_running_loop())

        class Socket:
            def __init__(self):
                self.messages = []

            async def send_json(self, payload):
                self.messages.append(payload)

        manager = ConnectionManager()
        project_id = uuid4()
        author_socket, collaborator_socket = Socket(), Socket()
        manager.sessions[project_id] = [
            ClientSession(author_socket, project_id, "user-author", "Author", "editor"),
            ClientSession(collaborator_socket, project_id, "user-peer", "Peer", "editor"),
        ]
        monkeypatch.setattr(
            "app.modules.diagram.infrastructure.realtime.broadcast_handler.connection_manager",
            manager,
        )
        WebSocketBroadcastEventHandler().handle(
            DiagramMutationEvent(
                project_id=project_id,
                sender_id="assistant",
                operation_type="CREATE_CLASS",
                data={"id": str(uuid4()), "name": "Producto"},
            )
        )
        await asyncio.sleep(0.05)
        assert len(author_socket.messages) == 1
        assert len(collaborator_socket.messages) == 1
        assert author_socket.messages[0] == collaborator_socket.messages[0]
        assert author_socket.messages[0]["sender_id"] == "assistant"

    asyncio.run(run())
