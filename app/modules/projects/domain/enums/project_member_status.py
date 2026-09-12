from enum import Enum


class ProjectMemberStatus(str, Enum):
    """Estado de participación de un colaborador en un proyecto."""

    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    BANNED = "BANNED"

    def is_active(self) -> bool:
        return self == ProjectMemberStatus.ACTIVE

    def is_removed(self) -> bool:
        return self == ProjectMemberStatus.REMOVED

    def is_banned(self) -> bool:
        return self == ProjectMemberStatus.BANNED
