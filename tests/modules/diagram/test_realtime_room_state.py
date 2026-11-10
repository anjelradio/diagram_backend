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


def test_agent_component_reservation_promotion_and_non_demotion() -> None:
    project_id = uuid4()
    message_id = uuid4()
    class_id = uuid4()
    room = ProjectRoomState(project_id, reservation_ttl_seconds=300)

    # 1. Reserva inicial en modo query
    res = room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="query",
        now=10,
    )
    assert res.activity_type == "query"
    assert res.sequence == 1
    assert room.is_component_reserved(class_id, "class", now=10)

    # 2. Promoción a modo edit
    res2 = room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=2,
        component_type="class",
        component_id=class_id,
        activity_type="edit",
        now=20,
    )
    assert res2.activity_type == "edit"
    assert res2.sequence == 2
    assert len(room.agent_reservations) == 1

    # 3. Consulta posterior no rebaja el modo edit
    res3 = room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=3,
        component_type="class",
        component_id=class_id,
        activity_type="query",
        now=30,
    )
    assert res3.activity_type == "edit"
    assert res3.sequence == 3
    assert len(room.agent_reservations) == 1


def test_agent_component_reservation_multiple_messages_and_selective_release() -> None:
    project_id = uuid4()
    msg1 = uuid4()
    msg2 = uuid4()
    class_id = uuid4()
    rel_id = uuid4()
    room = ProjectRoomState(project_id, reservation_ttl_seconds=300)

    # Ambos mensajes reservan la misma clase
    room.reserve_component(
        project_id=project_id,
        message_id=msg1,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="query",
        now=10,
    )
    room.reserve_component(
        project_id=project_id,
        message_id=msg2,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="edit",
        now=15,
    )
    room.reserve_component(
        project_id=project_id,
        message_id=msg1,
        sequence=2,
        component_type="relation",
        component_id=rel_id,
        activity_type="edit",
        now=20,
    )

    assert len(room.agent_reservations) == 3
    assert room.is_component_reserved(class_id, now=25)
    assert room.is_component_reserved(rel_id, now=25)

    # Liberar solo msg1
    released = room.release_message_reservations(msg1)
    assert len(released) == 2
    assert len(room.agent_reservations) == 1
    # La clase sigue reservada por msg2
    assert room.is_component_reserved(class_id, now=25)
    assert not room.is_component_reserved(rel_id, now=25)

    serialized = room.serialize_reservations()
    assert len(serialized) == 1
    assert serialized[0]["message_id"] == str(msg2)
    assert serialized[0]["component_id"] == str(class_id)
    assert serialized[0]["activity_type"] == "edit"


def test_agent_component_reservation_expiration() -> None:
    project_id = uuid4()
    message_id = uuid4()
    class_id = uuid4()
    room = ProjectRoomState(project_id, reservation_ttl_seconds=100)

    room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="query",
        now=0,
    )
    assert room.has_active_reservations(now=50)
    assert not room.check_expired_reservations(now=50)
    assert room.has_active_reservations(now=50)

    expired = room.check_expired_reservations(now=101)
    assert len(expired) == 1
    assert expired[0].component_id == class_id
    assert not room.has_active_reservations(now=101)

