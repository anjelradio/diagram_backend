from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.diagram.infrastructure.realtime.messages import (
    ClassDragMessage,
    ClassLockAcquireMessage,
    ClassLockReleaseMessage,
    CursorMoveMessage,
    PingMessage,
    diagram_mutation,
    parse_client_message,
    presence_snapshot,
)


def test_parse_client_message_accepts_all_client_messages() -> None:
    # 1. Ping
    assert isinstance(parse_client_message({"type": "ping"}), PingMessage)

    # 2. Cursor move
    cursor_msg = parse_client_message({"type": "cursor_move", "x": 100.5, "y": 200.0})
    assert isinstance(cursor_msg, CursorMoveMessage)
    assert cursor_msg.x == 100.5
    assert cursor_msg.y == 200.0

    # 3. Class drag
    class_id = uuid4()
    drag_msg = parse_client_message(
        {"type": "class_drag", "class_id": str(class_id), "x": 12.0, "y": 24.0}
    )
    assert isinstance(drag_msg, ClassDragMessage)
    assert drag_msg.class_id == class_id
    assert drag_msg.x == 12.0
    assert drag_msg.y == 24.0

    # 4. Class lock acquire
    lock_acquire = parse_client_message(
        {"type": "class_lock_acquire", "class_id": str(class_id)}
    )
    assert isinstance(lock_acquire, ClassLockAcquireMessage)
    assert lock_acquire.class_id == class_id

    # 5. Class lock release
    lock_release = parse_client_message(
        {"type": "class_lock_release", "class_id": str(class_id)}
    )
    assert isinstance(lock_release, ClassLockReleaseMessage)
    assert lock_release.class_id == class_id


@pytest.mark.parametrize("payload", [
    {"type": "unknown"},
    {"type": "cursor_move", "x": "invalid", "y": 1},
    {"type": "cursor_move", "x": 100.0},  # missing y
    {"type": "class_drag", "x": 10, "y": 10},  # missing class_id
    {"type": "class_drag", "class_id": "not-a-uuid", "x": 10, "y": 10},
    {"type": "class_lock_acquire"},  # missing class_id
    {"type": "ping", "unexpected": True},  # extra forbid
])
def test_parse_client_message_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_client_message(payload)


def test_server_message_helpers() -> None:
    # presence_snapshot format
    peers = [{"user_id": "u1", "user_name": "Alice", "role": "OWNER"}]
    locks = [{
        "class_id": str(uuid4()),
        "user_id": "u1",
        "user_name": "Alice",
        "locked_at": 1000.0,
        "expires_at": 1060.0,
    }]
    snapshot = presence_snapshot(peers, locks)
    assert snapshot["type"] == "presence_snapshot"
    assert snapshot["peers"] == peers
    assert snapshot["class_locks"] == locks

    # diagram_mutation format
    mutation = diagram_mutation("MOVE_CLASS", {"id": "c1", "x": 10, "y": 20}, "u1")
    assert mutation["type"] == "diagram_mutation"
    assert mutation["operation_type"] == "MOVE_CLASS"
    assert mutation["data"] == {"id": "c1", "x": 10, "y": 20}
    assert mutation["sender_id"] == "u1"

    active_lock = {"user_id": "assistant", "activity_id": str(uuid4())}
    recovered = presence_snapshot(peers, locks, active_lock)
    assert recovered["agent_lock"] == active_lock
