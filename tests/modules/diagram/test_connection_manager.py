import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import WebSocket

from app.modules.diagram.infrastructure.realtime.connection_manager import (
    ClientSession,
    ConnectionManager,
)


def test_connection_manager_connect_and_disconnect() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        ws1 = AsyncMock(spec=WebSocket)
        session1 = ClientSession(
            websocket=ws1,
            project_id=project_id,
            user_id="user_1",
            user_name="User 1",
            role="OWNER",
        )

        await manager.connect(session1)
        ws1.accept.assert_awaited_once()
        ws1.send_json.assert_awaited_once()
        assert project_id in manager.sessions
        assert len(manager.sessions[project_id]) == 1

        # Connect second user
        ws2 = AsyncMock(spec=WebSocket)
        session2 = ClientSession(
            websocket=ws2,
            project_id=project_id,
            user_id="user_2",
            user_name="User 2",
            role="EDITOR",
        )
        await manager.connect(session2)
        assert len(manager.sessions[project_id]) == 2

        # Disconnect first user
        released = await manager.disconnect(session1)
        assert released == []
        assert len(manager.sessions[project_id]) == 1

        # Disconnect second user (room becomes empty)
        await manager.disconnect(session2)
        assert project_id not in manager.sessions
        assert project_id not in manager.rooms

    asyncio.run(_run())


def test_connection_manager_broadcast_and_dead_socket_pruning() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()

        ws_alive = AsyncMock(spec=WebSocket)
        session_alive = ClientSession(
            websocket=ws_alive,
            project_id=project_id,
            user_id="user_alive",
            user_name="Alive",
            role="OWNER",
        )

        ws_dead = AsyncMock(spec=WebSocket)
        session_dead = ClientSession(
            websocket=ws_dead,
            project_id=project_id,
            user_id="user_dead",
            user_name="Dead",
            role="EDITOR",
        )

        await manager.connect(session_alive)
        await manager.connect(session_dead)

        # Now make ws_dead fail on subsequent send_json calls (during broadcast)
        ws_dead.send_json.side_effect = RuntimeError("Socket closed")

        # Broadcast message
        await manager.broadcast(project_id, {"type": "test_event"})

        # Dead socket should be pruned via disconnect
        assert len(manager.sessions.get(project_id, [])) == 1
        assert manager.sessions[project_id][0].user_id == "user_alive"

    asyncio.run(_run())


def test_connection_manager_lock_queries() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        class_id = uuid4()

        ws = AsyncMock(spec=WebSocket)
        session = ClientSession(
            websocket=ws,
            project_id=project_id,
            user_id="user_lock",
            user_name="Locker",
            role="OWNER",
        )
        await manager.connect(session)

        room = manager.rooms[project_id]
        lock = room.acquire_lock(class_id, "user_lock", "Locker")
        assert lock is not None

        assert manager.is_class_locked_by_other(project_id, class_id, "user_lock") is False
        assert manager.is_class_locked_by_other(project_id, class_id, "other_user") is True

        owner = manager.lock_owner(project_id, class_id)
        assert owner is not None
        assert owner.user_id == "user_lock"

    asyncio.run(_run())


def test_connection_manager_multi_session_first_and_last_session_behavior() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        class_id = uuid4()

        # Usuario Bob (observador)
        ws_bob = AsyncMock(spec=WebSocket)
        session_bob = ClientSession(
            websocket=ws_bob,
            project_id=project_id,
            user_id="bob",
            user_name="Bob",
            role="EDITOR",
        )
        await manager.connect(session_bob)

        # Alice abre pestaña 1 (primera sesión)
        ws_alice1 = AsyncMock(spec=WebSocket)
        session_alice1 = ClientSession(
            websocket=ws_alice1,
            project_id=project_id,
            user_id="alice",
            user_name="Alice",
            role="OWNER",
        )
        await manager.connect(session_alice1)

        # Bob debe recibir user_joined de Alice
        ws_bob.send_json.assert_any_await({"type": "user_joined", "user_id": "alice", "user_name": "Alice", "role": "OWNER"})
        ws_bob.send_json.reset_mock()

        # Alice adquiere un lock en pestaña 1
        room = manager.rooms[project_id]
        lock = room.acquire_lock(class_id, "alice", "Alice")
        assert lock is not None

        # Alice abre pestaña 2 (segunda sesión del mismo usuario)
        ws_alice2 = AsyncMock(spec=WebSocket)
        session_alice2 = ClientSession(
            websocket=ws_alice2,
            project_id=project_id,
            user_id="alice",
            user_name="Alice",
            role="OWNER",
        )
        await manager.connect(session_alice2)

        # Bob NO debe recibir otro user_joined para la segunda pestaña de Alice
        for call in ws_bob.send_json.await_args_list:
            assert call.args[0].get("type") != "user_joined"

        # Alice cierra pestaña 1 (no es la última sesión)
        released_first = await manager.disconnect(session_alice1)
        # El lock NO debe liberarse
        assert released_first == []
        assert manager.is_class_locked_by_other(project_id, class_id, "bob") is True

        # Bob NO debe recibir user_left todavía
        for call in ws_bob.send_json.await_args_list:
            assert call.args[0].get("type") != "user_left"

        # Alice cierra pestaña 2 (última sesión)
        ws_bob.send_json.reset_mock()
        released_last = await manager.disconnect(session_alice2)
        assert class_id in released_last
        assert manager.is_class_locked_by_other(project_id, class_id, "bob") is False

        # Bob debe recibir class_unlocked y user_left
        ws_bob.send_json.assert_any_await({"type": "class_unlocked", "class_id": str(class_id), "user_id": "alice"})
        ws_bob.send_json.assert_any_await({"type": "user_left", "user_id": "alice"})

    asyncio.run(_run())


def test_connection_manager_disconnect_is_idempotent() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        ws = AsyncMock(spec=WebSocket)
        session = ClientSession(
            websocket=ws,
            project_id=project_id,
            user_id="user_1",
            user_name="User 1",
            role="OWNER",
        )
        await manager.connect(session)

        # Primera desconexión
        released1 = await manager.disconnect(session)
        assert released1 == []

        # Segunda desconexión redundante
        released2 = await manager.disconnect(session)
        assert released2 == []

    asyncio.run(_run())


def test_connection_manager_broadcasts_correlated_agent_lock_and_finish() -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        activity_id = uuid4()
        ws = AsyncMock(spec=WebSocket)
        session = ClientSession(
            websocket=ws,
            project_id=project_id,
            user_id="editor",
            user_name="Editor",
            role="EDITOR",
        )
        await manager.connect(session)
        ws.send_json.reset_mock()

        await manager.broadcast_agent_lock(project_id, "owner", activity_id)
        ws.send_json.assert_awaited_once_with(
            {"type": "agent_lock", "user_id": "owner", "activity_id": str(activity_id)}
        )
        ws.send_json.reset_mock()

        await manager.broadcast_agent_finished(project_id, "owner", activity_id, "FINISHED")
        ws.send_json.assert_awaited_once_with(
            {
                "type": "agent_finished",
                "user_id": "owner",
                "activity_id": str(activity_id),
                "state": "FINISHED",
            }
        )

    asyncio.run(_run())


def test_connection_manager_revalidate_access_revocation_closes_1008(monkeypatch) -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        ws = AsyncMock(spec=WebSocket)
        session = ClientSession(
            websocket=ws,
            project_id=project_id,
            user_id="revoked_user",
            user_name="Revoked",
            role="EDITOR",
        )
        await manager.connect(session)

        # Mock get_ws_project_access to raise HTTPException / 403
        def mock_get_access(*args, **kwargs):
            raise RuntimeError("Access revoked")

        monkeypatch.setattr(
            "app.modules.diagram.infrastructure.api.dependencies.ws_auth.get_ws_project_access",
            mock_get_access,
        )

        await manager.revalidate_accesses()

        # Debe cerrar el socket con código 1008 y desconectar la sesión
        ws.close.assert_awaited_once_with(code=1008)
        assert project_id not in manager.sessions

    asyncio.run(_run())


def test_connection_manager_revalidate_access_role_degradation_releases_locks(monkeypatch) -> None:
    async def _run() -> None:
        manager = ConnectionManager()
        project_id = uuid4()
        class_id = uuid4()
        ws = AsyncMock(spec=WebSocket)
        session = ClientSession(
            websocket=ws,
            project_id=project_id,
            user_id="editor_user",
            user_name="Editor",
            role="EDITOR",
        )
        await manager.connect(session)

        # Adquirir un lock
        room = manager.rooms[project_id]
        room.acquire_lock(class_id, "editor_user", "Editor")
        assert manager.is_class_locked_by_other(project_id, class_id, "other_user") is True

        # Mock get_ws_project_access returning READER role
        from unittest.mock import MagicMock
        from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
        mock_access = MagicMock()
        mock_access.access_role = ProjectAccessRole.READER

        monkeypatch.setattr(
            "app.modules.diagram.infrastructure.api.dependencies.ws_auth.get_ws_project_access",
            lambda *args, **kwargs: mock_access,
        )

        await manager.revalidate_accesses()

        # Debe actualizar rol a READER, liberar locks y enviar role_changed
        assert session.role == "READER"
        assert manager.is_class_locked_by_other(project_id, class_id, "other_user") is False
        ws.send_json.assert_any_await({"type": "role_changed", "role": "READER"})
        ws.send_json.assert_any_await({"type": "class_unlocked", "class_id": str(class_id), "user_id": "editor_user"})

    asyncio.run(_run())

