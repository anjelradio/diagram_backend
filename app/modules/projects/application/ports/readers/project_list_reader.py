from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProjectListItem:
    """Elemento proyectado del listado de proyectos."""

    id: UUID
    name: str
    description: str | None
    thumbnail_url: str | None
    is_owner: bool


class ProjectListReader(ABC):
    """Puerto de lectura para obtener el espacio de proyectos de un usuario."""

    @abstractmethod
    def list_projects_for_user(self, user_id: str) -> list[ProjectListItem]:
        """Obtiene en una sola consulta los proyectos propios y las participaciones activas del usuario."""
        raise NotImplementedError
