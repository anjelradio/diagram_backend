"""Estado efímero y serializable de una sala de colaboración."""

from dataclasses import dataclass
from uuid import UUID


@dataclass
class ClassLock:
    class_id: UUID
    user_id: str
    user_name: str
    locked_at: float
    expires_at: float


@dataclass
class AgentComponentReservation:
    project_id: UUID
    message_id: UUID
    sequence: int
    component_type: str  # "class" | "relation"
    component_id: UUID
    activity_type: str  # "query" | "edit"
    attribute_id: UUID | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float = 0.0


class ProjectRoomState:
    """Coordina bloqueos de clases y reservas efímeras de componentes del agente."""

    def __init__(
        self,
        project_id: UUID,
        lock_ttl_seconds: float = 60.0,
        reservation_ttl_seconds: float = 300.0,
    ) -> None:
        self.project_id = project_id
        self.lock_ttl_seconds = lock_ttl_seconds
        self.reservation_ttl_seconds = reservation_ttl_seconds
        self.class_locks: dict[UUID, ClassLock] = {}
        self.agent_reservations: dict[tuple[UUID, str, UUID], AgentComponentReservation] = {}

    def acquire_lock(
        self,
        class_id: UUID,
        user_id: str,
        user_name: str,
        now: float | None = None,
    ) -> ClassLock | None:
        import time

        current = time.monotonic() if now is None else now
        self.check_expired_locks(current)
        owned = next((lock for lock in self.class_locks.values() if lock.user_id == user_id), None)
        if owned is not None and owned.class_id != class_id:
            self.release_lock(owned.class_id, user_id)
        existing = self.class_locks.get(class_id)
        if existing is not None and existing.user_id != user_id:
            return None
        lock = ClassLock(class_id, user_id, user_name, current, current + self.lock_ttl_seconds)
        self.class_locks[class_id] = lock
        return lock

    def release_lock(self, class_id: UUID, user_id: str) -> bool:
        lock = self.class_locks.get(class_id)
        if lock is None or lock.user_id != user_id:
            return False
        del self.class_locks[class_id]
        return True

    def release_user_locks(self, user_id: str) -> list[ClassLock]:
        released = [lock for lock in self.class_locks.values() if lock.user_id == user_id]
        for lock in released:
            self.class_locks.pop(lock.class_id, None)
        return released

    def check_expired_locks(self, now: float | None = None) -> list[ClassLock]:
        import time

        current = time.monotonic() if now is None else now
        expired = [lock for lock in self.class_locks.values() if lock.expires_at <= current]
        for lock in expired:
            self.class_locks.pop(lock.class_id, None)
        return expired

    def serialize_locks(self) -> list[dict[str, object]]:
        return [
            {
                "class_id": str(lock.class_id),
                "user_id": lock.user_id,
                "user_name": lock.user_name,
                "locked_at": lock.locked_at,
                "expires_at": lock.expires_at,
            }
            for lock in self.class_locks.values()
        ]

    def reserve_component(
        self,
        *,
        project_id: UUID,
        message_id: UUID,
        sequence: int,
        component_type: str,
        component_id: UUID,
        activity_type: str,
        attribute_id: UUID | None = None,
        now: float | None = None,
    ) -> AgentComponentReservation:
        import time

        current = time.monotonic() if now is None else now
        self.check_expired_reservations(current)
        key = (message_id, component_type, component_id)
        existing = self.agent_reservations.get(key)
        if existing is not None:
            effective_activity = (
                "edit"
                if (existing.activity_type == "edit" or activity_type == "edit")
                else "query"
            )
            if sequence < existing.sequence:
                effective_attr_id = (
                    existing.attribute_id if existing.attribute_id is not None else attribute_id
                )
                effective_sequence = existing.sequence
            else:
                effective_attr_id = (
                    attribute_id if attribute_id is not None else existing.attribute_id
                )
                effective_sequence = sequence
            existing.activity_type = effective_activity
            existing.attribute_id = effective_attr_id
            existing.sequence = effective_sequence
            existing.updated_at = current
            existing.expires_at = current + self.reservation_ttl_seconds
            return existing

        reservation = AgentComponentReservation(
            project_id=project_id,
            message_id=message_id,
            sequence=sequence,
            component_type=component_type,
            component_id=component_id,
            activity_type=activity_type,
            attribute_id=attribute_id,
            created_at=current,
            updated_at=current,
            expires_at=current + self.reservation_ttl_seconds,
        )
        self.agent_reservations[key] = reservation
        return reservation

    def release_message_reservations(
        self, message_id: UUID
    ) -> list[AgentComponentReservation]:
        released = [
            res
            for key, res in list(self.agent_reservations.items())
            if key[0] == message_id
        ]
        for res in released:
            self.agent_reservations.pop(
                (res.message_id, res.component_type, res.component_id), None
            )
        return released

    def check_expired_reservations(
        self, now: float | None = None
    ) -> list[AgentComponentReservation]:
        import time

        current = time.monotonic() if now is None else now
        expired = [
            res
            for res in self.agent_reservations.values()
            if res.expires_at <= current
        ]
        for res in expired:
            self.agent_reservations.pop(
                (res.message_id, res.component_type, res.component_id), None
            )
        return expired

    def has_active_reservations(self, now: float | None = None) -> bool:
        self.check_expired_reservations(now)
        return bool(self.agent_reservations)

    def is_component_reserved(
        self,
        component_id: UUID,
        component_type: str | None = None,
        now: float | None = None,
    ) -> bool:
        self.check_expired_reservations(now)
        return any(
            res.component_id == component_id
            and (component_type is None or res.component_type == component_type)
            for res in self.agent_reservations.values()
        )

    def serialize_reservations(self, now: float | None = None) -> list[dict[str, object]]:
        if now is not None:
            self.check_expired_reservations(now)
        return [
            {
                "project_id": str(res.project_id),
                "message_id": str(res.message_id),
                "sequence": res.sequence,
                "component_type": res.component_type,
                "component_id": str(res.component_id),
                "activity_type": res.activity_type,
                "attribute_id": str(res.attribute_id) if res.attribute_id is not None else None,
            }
            for res in self.agent_reservations.values()
        ]

