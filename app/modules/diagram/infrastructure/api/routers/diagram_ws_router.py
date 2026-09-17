"""Endpoint WebSocket para presencia y eventos efímeros del diagrama."""

from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException
from sqlmodel import Session

from app.core.database import engine
from app.modules.diagram.infrastructure.api.dependencies.ws_auth import (
    get_ws_auth_user,
    get_ws_project_access,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    ClientSession,
    connection_manager,
)
from app.modules.diagram.infrastructure.realtime.messages import (
    ClassDragMessage,
    ClassLockAcquireMessage,
    ClassLockReleaseMessage,
    CursorMoveMessage,
    PingMessage,
    parse_client_message,
)
from app.modules.diagram.infrastructure.realtime.rate_limiter import CursorRateLimiter
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole

ws_router = APIRouter(tags=["diagram-realtime"])


@ws_router.websocket("/ws/projects/{project_id}")
async def diagram_websocket(
    websocket: WebSocket,
    project_id: UUID,
) -> None:
    """Autentica la sala, distribuye eventos y limpia la sesión al salir."""
    user = get_ws_auth_user(websocket)
    with Session(engine) as db:
        access = get_ws_project_access(db, project_id, user)
    role = access.access_role.value
    session = ClientSession(
        websocket=websocket,
        project_id=project_id,
        user_id=user.user_id,
        user_name=user.name or user.user_id,
        role=role,
        rate_limiter=CursorRateLimiter(),
    )
    await connection_manager.connect(session)
    try:
        while True:
            payload = await websocket.receive_json()
            session.last_heartbeat = __import__("time").monotonic()
            try:
                message = parse_client_message(payload)
            except Exception:
                await websocket.send_json({"type": "error", "code": "INVALID_MESSAGE"})
                continue

            if isinstance(message, PingMessage):
                await websocket.send_json({"type": "pong"})
                continue

            if isinstance(message, CursorMoveMessage):
                if session.role == ProjectAccessRole.READER.value or not session.rate_limiter.allow():
                    continue
                await connection_manager.broadcast(
                    project_id,
                    {"type": "cursor_moved", "user_id": user.user_id, "user_name": session.user_name, "x": message.x, "y": message.y},
                    exclude_user_id=user.user_id,
                )
                continue

            if isinstance(message, ClassDragMessage):
                if session.role == ProjectAccessRole.READER.value or not session.rate_limiter.allow():
                    continue
                room = connection_manager.rooms.get(project_id)
                lock = room.class_locks.get(message.class_id) if room else None
                if lock is None or lock.user_id != user.user_id:
                    continue
                lock.expires_at = session.last_heartbeat + (room.lock_ttl_seconds if room else 60.0)
                await connection_manager.broadcast(
                    project_id,
                    {"type": "class_dragged", "class_id": str(message.class_id), "x": message.x, "y": message.y, "user_id": user.user_id, "user_name": session.user_name},
                    exclude_user_id=user.user_id,
                )
                continue

            room = connection_manager.rooms.get(project_id)
            if room is None:
                continue
            if isinstance(message, ClassLockAcquireMessage):
                if session.role == ProjectAccessRole.READER.value:
                    continue
                lock = room.acquire_lock(message.class_id, user.user_id, session.user_name)
                if lock is None:
                    owner = connection_manager.lock_owner(project_id, message.class_id)
                    await websocket.send_json({
                        "type": "class_lock_denied",
                        "class_id": str(message.class_id),
                        "user_id": owner.user_id if owner else None,
                        "user_name": owner.user_name if owner else None,
                    })
                else:
                    await connection_manager.broadcast(
                        project_id,
                        {
                            "type": "class_locked",
                            "class_id": str(lock.class_id),
                            "user_id": lock.user_id,
                            "user_name": lock.user_name,
                            "locked_at": lock.locked_at,
                            "expires_at": lock.expires_at,
                        },
                    )
                continue

            if isinstance(message, ClassLockReleaseMessage):
                if room.release_lock(message.class_id, user.user_id):
                    await connection_manager.broadcast(
                        project_id,
                        {"type": "class_unlocked", "class_id": str(message.class_id), "user_id": user.user_id},
                    )
    except WebSocketDisconnect:
        pass
    except WebSocketException:
        raise
    finally:
        await connection_manager.disconnect(session)
