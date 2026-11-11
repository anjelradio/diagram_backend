from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)


class DiagramAuditLogRepository(ABC):
    """Contrato de persistencia para la entidad DiagramAuditLog."""

    @abstractmethod
    def save(self, audit_log: DiagramAuditLog) -> None:
        """Persiste una entrada de bitácora en la sesión activa."""
        pass

    @abstractmethod
    def find_by_id(self, audit_log_id: UUID) -> DiagramAuditLog | None:
        """Busca una entrada de bitácora por su identificador primario."""
        pass

    @abstractmethod
    def list_by_project(
        self,
        project_id: UUID,
        *,
        user_id: str | None = None,
        user_search: str | None = None,
        actor_type: DiagramAuditActorType | None = None,
        entity_type: DiagramAuditEntityType | None = None,
        entity_id: UUID | None = None,
        entity_name: str | None = None,
        parent_class_id: UUID | None = None,
        parent_class_name: str | None = None,
        action: DiagramAuditAction | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiagramAuditLog]:
        """Lista entradas de bitácora de un proyecto ordenadas de más reciente a más antigua."""
        pass
