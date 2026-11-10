from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.integrations.domain.entities.project_integration import (
    ProjectIntegration,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)


class ProjectIntegrationRepository(ABC):
    """Puerto de persistencia para integraciones de proyectos."""

    @abstractmethod
    def save(self, integration: ProjectIntegration) -> ProjectIntegration:
        """Crea o actualiza la integración de un proyecto."""

    @abstractmethod
    def find_by_id(self, integration_id: UUID) -> ProjectIntegration | None:
        """Busca una integración activa por su identificador único."""

    @abstractmethod
    def find_by_project_and_provider(
        self,
        project_id: UUID,
        provider: IntegrationProvider,
    ) -> ProjectIntegration | None:
        """Busca la integración activa de un proyecto para un proveedor específico."""
