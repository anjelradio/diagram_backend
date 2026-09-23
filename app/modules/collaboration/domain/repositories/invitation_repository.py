from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.collaboration.domain.entities.invitation import Invitation


class InvitationRepository(ABC):
    """Contrato del repositorio para la persistencia y consulta de invitaciones."""

    @abstractmethod
    def save(self, invitation: Invitation) -> None:
        """Guarda o actualiza la invitación."""
        raise NotImplementedError

    @abstractmethod
    def find_by_project_id(self, project_id: UUID) -> Invitation | None:
        """Obtiene la invitación asociada al proyecto."""
        raise NotImplementedError

    @abstractmethod
    def find_by_code(self, code: str) -> Invitation | None:
        """Busca una invitación por su código único."""
        raise NotImplementedError
