from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramSnapshotDto,
    DiagramSnapshotReader,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)


@dataclass(frozen=True, slots=True)
class GetDiagramQuery:
    """Consulta para obtener el snapshot del diagrama completo de un proyecto."""

    project_id: UUID
    user_id: str


class GetDiagramQueryHandler:
    """Manejador de consulta para obtener clases con atributos y permisos."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        diagram_snapshot_reader: DiagramSnapshotReader,
    ) -> None:
        self.access_policy = access_policy
        self.diagram_snapshot_reader = diagram_snapshot_reader

    def execute(self, query: GetDiagramQuery) -> DiagramSnapshotDto:
        # 1. Autorización de lectura
        self.access_policy.ensure_read_access(
            query.project_id, query.user_id
        )

        # 2. Recuperar clases con atributos ordenados y relaciones mediante el Reader especializado
        classes = (
            self.diagram_snapshot_reader.get_classes_with_attributes_by_project_id(
                query.project_id
            )
        )
        relations = (
            self.diagram_snapshot_reader.get_relations_by_project_id(
                query.project_id
            )
        )

        return DiagramSnapshotDto(classes=classes, relations=relations)

