from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.projects.domain.entities.project_member import ProjectMember


class ProjectMemberRepository(ABC):
    """Contrato del repositorio para la persistencia y consulta de participantes."""

    @abstractmethod
    def save(self, member: ProjectMember) -> None:
        """Guarda o actualiza la participación del colaborador."""
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, member_id: UUID) -> ProjectMember | None:
        """Busca una participación por su identificador único."""
        raise NotImplementedError

    @abstractmethod
    def find_by_project_and_user(
        self, project_id: UUID, user_id: str
    ) -> ProjectMember | None:
        """Busca la participación de un usuario en un proyecto."""
        raise NotImplementedError
