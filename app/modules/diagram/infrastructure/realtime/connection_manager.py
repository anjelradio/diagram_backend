"""Gestor de conexiones y salas efímeras del WebSocket de Diagram."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from fastapi import WebSocket

from .room_state import ProjectRoomState


@dataclass
class ClientSession:
    websocket: WebSocket
    project_id: UUID
    user_id: str
    user_name: str
    role: str
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: float = field(default_factory=time.monotonic)
    rate_limiter: object | None = None

    def presence(self) -> dict[str, object]:
        return {"user_id": self.user_id, "user_name": self.user_name, "role": self.role}


class ConnectionManager:
    """Singleton lógico de salas; preparado para sustituirse por un bus distribuido."""

    def __init__(self) -> None:
        self.sessions: dict[UUID, list[ClientSession]] = {}
        self.rooms: dict[UUID, ProjectRoomState] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session: ClientSession) -> None:
        await session.websocket.accept()
        async with self._lock:
            room = self.rooms.setdefault(session.project_id, ProjectRoomState(session.project_id))
            peers = [peer.presence() for peer in self.sessions.get(session.project_id, [])]
            self.sessions.setdefault(session.project_id, []).append(session)
        await session.websocket.send_json(
            {
                "type": "presence_snapshot",
                "peers": peers + [session.presence()],
                "class_locks": room.serialize_locks(),
            }
        )
        await self.broadcast(
            session.project_id,
            {"type": "user_joined", **session.presence()},
            exclude_user_id=session.user_id,
        )

    async def disconnect(self, session: ClientSession) -> list[UUID]:
        async with self._lock:
            peers = self.sessions.get(session.project_id, [])
            self.sessions[session.project_id] = [peer for peer in peers if peer is not session]
            room = self.rooms.get(session.project_id)
            released = room.release_user_locks(session.user_id) if room else []
            if not self.sessions[session.project_id]:
                self.sessions.pop(session.project_id, None)
                self.rooms.pop(session.project_id, None)
        for lock in released:
            await self.broadcast(
                session.project_id,
                {"type": "class_unlocked", "class_id": str(lock.class_id), "user_id": lock.user_id},
            )
        await self.broadcast(
            session.project_id,
            {"type": "user_left", **session.presence()},
            exclude_user_id=session.user_id,
        )
        return [lock.class_id for lock in released]

    async def broadcast(
        self,
        project_id: UUID,
        payload: dict[str, object],
        exclude_user_id: str | None = None,
    ) -> None:
        peers = [
            peer
            for peer in self.sessions.get(project_id, [])
            if exclude_user_id is None or peer.user_id != exclude_user_id
        ]
        if not peers:
            return
        results = await asyncio.gather(
            *(peer.websocket.send_json(payload) for peer in peers),
            return_exceptions=True,
        )
        dead = [peer for peer, result in zip(peers, results) if isinstance(result, Exception)]
        if dead:
            async with self._lock:
                current = self.sessions.get(project_id, [])
                self.sessions[project_id] = [peer for peer in current if peer not in dead]

    async def close_stale(self, timeout_seconds: float = 60.0) -> None:
        now = time.monotonic()
        stale = [
            session
            for peers in self.sessions.values()
            for session in peers
            if now - session.last_heartbeat > timeout_seconds
        ]
        for session in stale:
            try:
                await session.websocket.close(code=1001)
            finally:
                await self.disconnect(session)

    async def monitor_stale_connections(self, interval_seconds: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            await self.close_stale()
            for project_id, room in list(self.rooms.items()):
                expired = room.check_expired_locks()
                for lock in expired:
                    await self.broadcast(
                        project_id,
                        {"type": "class_unlocked", "class_id": str(lock.class_id), "user_id": lock.user_id},
                    )


connection_manager = ConnectionManager()
