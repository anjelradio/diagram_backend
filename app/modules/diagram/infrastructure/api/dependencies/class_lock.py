"""Dependencia de infraestructura para impedir escrituras sobre clases bloqueadas."""

from uuid import UUID

from fastapi import HTTPException, status

from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import connection_manager


def ensure_class_is_editable(
    repository: DiagramClassRepository,
    class_id: UUID,
    user_id: str,
) -> None:
    """Rechaza la mutación durable si otro colaborador posee el bloqueo vigente."""
    diagram_class = repository.find_by_id(class_id)
    if diagram_class is None:
        return
    if connection_manager.is_class_locked_by_other(
        diagram_class.project_id, class_id, user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="La clase está siendo editada por otro colaborador.",
        )
