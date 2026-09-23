from enum import Enum


class ProjectMemberRole(str, Enum):
    """Rol de un colaborador dentro de un proyecto."""

    READER = "READER"
    EDITOR = "EDITOR"

    def is_reader(self) -> bool:
        return self == ProjectMemberRole.READER

    def is_editor(self) -> bool:
        return self == ProjectMemberRole.EDITOR
