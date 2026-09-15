from uuid import uuid4

from app.modules.diagram.infrastructure.realtime.room_state import ProjectRoomState


def test_room_allows_one_lock_per_editor_and_releases_previous_lock() -> None:
    room = ProjectRoomState(uuid4(), lock_ttl_seconds=60)
    first, second = uuid4(), uuid4()
    assert room.acquire_lock(first, "editor", "Editora", now=0) is not None
    assert room.acquire_lock(second, "editor", "Editora", now=1) is not None
    assert first not in room.class_locks
    assert second in room.class_locks


def test_room_denies_other_editor_and_expires_locks() -> None:
    room = ProjectRoomState(uuid4(), lock_ttl_seconds=60)
    class_id = uuid4()
    assert room.acquire_lock(class_id, "one", "Uno", now=0) is not None
    assert room.acquire_lock(class_id, "two", "Dos", now=1) is None
    expired = room.check_expired_locks(now=61)
    assert [lock.class_id for lock in expired] == [class_id]
    assert room.acquire_lock(class_id, "two", "Dos", now=62) is not None
