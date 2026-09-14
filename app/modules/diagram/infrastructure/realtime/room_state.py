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


class ProjectRoomState:
    """Coordina bloqueos de clases con resolución first-come-first-served."""

    def __init__(self, project_id: UUID, lock_ttl_seconds: float = 60.0) -> None:
        self.project_id = project_id
        self.lock_ttl_seconds = lock_ttl_seconds
        self.class_locks: dict[UUID, ClassLock] = {}

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
            }
            for lock in self.class_locks.values()
        ]
