"""Gestor de conexiones y salas efímeras del WebSocket de Diagram."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from fastapi import WebSocket

from .room_state import ClassLock, ProjectRoomState


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

    @staticmethod
    def _rehydrate_agent_lock(project_id: UUID, room: ProjectRoomState) -> None:
        """Recupera un lock persistido cuando la sala se crea tras una reconexión."""
        if room.agent_lock is not None:
            return
        try:
            from sqlmodel import Session

            from app.core.database import engine
            from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
                SQLModelAgentActivityRepository,
            )

            with Session(engine) as db:
                activity = SQLModelAgentActivityRepository(db).find_active_by_project_id(
                    project_id
                )
            if activity is not None:
                # AgentActivity no almacena el iniciador; el identificador de
                # actividad sigue siendo la correlación autoritativa.
                room.set_agent_lock("assistant", activity.id)
        except Exception:
            # La conexión no debe fallar por una consulta de recuperación. El
            # monitor/cliente podrá reintentar en la siguiente reconexión.
            return

    async def connect(self, session: ClientSession) -> None:
        await session.websocket.accept()
        async with self._lock:
            room = self.rooms.setdefault(session.project_id, ProjectRoomState(session.project_id))
            self._rehydrate_agent_lock(session.project_id, room)
            peers = self.sessions.setdefault(session.project_id, [])
            is_first_session = not any(p.user_id == session.user_id for p in peers)
            
            # Deduplicar presencia por user_id para el snapshot inicial
            seen_users = {session.user_id: session.presence()}
            for peer in peers:
                if peer.user_id not in seen_users:
                    seen_users[peer.user_id] = peer.presence()
            
            peers.append(session)

        await session.websocket.send_json(
            {
                "type": "presence_snapshot",
                "peers": list(seen_users.values()),
                "class_locks": room.serialize_locks(),
                "agent_lock": room.agent_lock,
            }
        )
        if is_first_session:
            await self.broadcast(
                session.project_id,
                {"type": "user_joined", **session.presence()},
                exclude_user_id=session.user_id,
            )

    async def disconnect(self, session: ClientSession) -> list[UUID]:
        async with self._lock:
            peers = self.sessions.get(session.project_id, [])
            if session not in peers:
                return []
            self.sessions[session.project_id] = [p for p in peers if p is not session]
            is_last_session = not any(p.user_id == session.user_id for p in self.sessions[session.project_id])
            room = self.rooms.get(session.project_id)
            released = []
            if is_last_session and room is not None:
                released = room.release_user_locks(session.user_id)
            if not self.sessions[session.project_id]:
                self.sessions.pop(session.project_id, None)
                self.rooms.pop(session.project_id, None)

        for lock in released:
            await self.broadcast(
                session.project_id,
                {"type": "class_unlocked", "class_id": str(lock.class_id), "user_id": lock.user_id},
            )
        if is_last_session:
            await self.broadcast(
                session.project_id,
                {"type": "user_left", "user_id": session.user_id},
                exclude_user_id=session.user_id,
            )
        return [lock.class_id for lock in released]

    def is_class_locked_by_other(
        self, project_id: UUID, class_id: UUID, user_id: str
    ) -> bool:
        """Indica si una clase está reservada por otro colaborador activo."""
        room = self.rooms.get(project_id)
        if room is None:
            return False
        room.check_expired_locks()
        lock = room.class_locks.get(class_id)
        return lock is not None and lock.user_id != user_id

    def lock_owner(self, project_id: UUID, class_id: UUID) -> ClassLock | None:
        """Obtiene el bloqueo vigente de una clase para informar un rechazo."""
        room = self.rooms.get(project_id)
        if room is None:
            return None
        room.check_expired_locks()
        return room.class_locks.get(class_id)

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
        for peer in dead:
            await self.disconnect(peer)

    async def broadcast_agent_lock(
        self, project_id: UUID, user_id: str, activity_id: UUID
    ) -> None:
        """Notifica a todos los colaboradores que el agente IA ha bloqueado el lienzo."""
        room = self.rooms.setdefault(project_id, ProjectRoomState(project_id))
        room.set_agent_lock(user_id, activity_id)
        await self.broadcast(
            project_id,
            {
                "type": "agent_lock",
                "user_id": user_id,
                "activity_id": str(activity_id),
            },
        )

    async def broadcast_agent_finished(
        self, project_id: UUID, user_id: str, activity_id: UUID, state: str
    ) -> None:
        """Notifica a todos los colaboradores que el agente IA finalizó y liberó el lienzo."""
        room = self.rooms.get(project_id)
        if room is not None:
            room.release_agent_lock(activity_id)
        await self.broadcast(
            project_id,
            {
                "type": "agent_finished",
                "user_id": user_id,
                "activity_id": str(activity_id),
                "state": state,
            },
        )

    async def close_stale(self, timeout_seconds: float = 60.0) -> None:
        now = time.monotonic()
        stale = [
            session
            for peers in list(self.sessions.values())
            for session in list(peers)
            if now - session.last_heartbeat > timeout_seconds
        ]
        for session in stale:
            try:
                await session.websocket.close(code=1001)
            except Exception:
                pass
            finally:
                await self.disconnect(session)

    async def monitor_stale_connections(self, interval_seconds: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            await self.close_stale()
            await self.revalidate_accesses()
            for project_id, room in list(self.rooms.items()):
                expired = room.check_expired_locks()
                for lock in expired:
                    await self.broadcast(
                        project_id,
                        {"type": "class_unlocked", "class_id": str(lock.class_id), "user_id": lock.user_id},
                    )

    async def revalidate_accesses(self) -> None:
        """Expulsa miembros sin acceso y aplica inmediatamente un cambio de rol."""
        from sqlmodel import Session

        from app.core.database import engine
        from app.core.security.auth import AuthUser
        from app.modules.diagram.infrastructure.api.dependencies.ws_auth import (
            get_ws_project_access,
        )
        from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole

        sessions = [session for peers in list(self.sessions.values()) for session in list(peers)]
        for session in sessions:
            try:
                with Session(engine) as db:
                    access = get_ws_project_access(
                        db,
                        session.project_id,
                        AuthUser(user_id=session.user_id, email="", name=session.user_name, role=session.role),
                    )
            except Exception:
                try:
                    await session.websocket.close(code=1008)
                except Exception:
                    pass
                await self.disconnect(session)
                continue

            next_role = access.access_role.value
            if next_role == session.role:
                continue
            session.role = next_role
            if next_role == ProjectAccessRole.READER.value:
                room = self.rooms.get(session.project_id)
                released = room.release_user_locks(session.user_id) if room else []
                for lock in released:
                    await self.broadcast(
                        session.project_id,
                        {"type": "class_unlocked", "class_id": str(lock.class_id), "user_id": session.user_id},
                    )
            try:
                await session.websocket.send_json({"type": "role_changed", "role": next_role})
            except Exception:
                await self.disconnect(session)


connection_manager = ConnectionManager()
