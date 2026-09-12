from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.projects.domain.entities.project import Project


class ProjectRepository(ABC):
    """Contrato del repositorio para la persistencia y consulta de proyectos."""

    @abstractmethod
    def save(self, project: Project) -> None:
        """Guarda o actualiza la entidad del proyecto."""
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, project_id: UUID) -> Project | None:
        """Busca un proyecto por ID que no esté eliminado lógicamente."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, project_id: UUID) -> None:
        """Elimina un proyecto por su identificador único."""
        raise NotImplementedError

