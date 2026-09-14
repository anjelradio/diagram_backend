from enum import Enum


class ProjectAccessRole(str, Enum):
    """Rol de acceso efectivo de un usuario en un proyecto."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    READER = "READER"
