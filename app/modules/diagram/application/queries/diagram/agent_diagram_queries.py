"""Manejadores CQRS para consulta selectiva del diagrama por el agente."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.diagram.application.ports.readers.agent_diagram_reader import (
    AgentDiagramReader,
    DiagramElementDetailDto,
    DiagramElementSearchDto,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)


@dataclass(frozen=True, slots=True)
class SearchAgentDiagramQuery:
    """Búsqueda acotada de clases, atributos o relaciones por nombre."""

    project_id: UUID
    user_id: str
    query: str
    types: tuple[str, ...]
    limit: int = 10
    offset: int = 0


@dataclass(frozen=True, slots=True)
class GetAgentDiagramElementQuery:
    """Detalle de una entidad identificada por UUID dentro del proyecto."""

    project_id: UUID
    user_id: str
    element_type: str
    element_id: UUID


class AgentDiagramQueryHandler:
    """Aplica control de acceso y delega las proyecciones en un reader acotado."""

    MAX_LIMIT = 50

    def __init__(
        self, access_policy: DiagramAccessPolicy, reader: AgentDiagramReader
    ) -> None:
        self.access_policy = access_policy
        self.reader = reader

    def search(self, query: SearchAgentDiagramQuery) -> DiagramElementSearchDto:
        self.access_policy.ensure_read_access(query.project_id, query.user_id)
        limit = min(max(query.limit, 1), self.MAX_LIMIT)
        offset = max(query.offset, 0)
        return self.reader.search_elements(
            project_id=query.project_id,
            query=query.query.strip(),
            types=query.types,
            limit=limit,
            offset=offset,
        )

    def get(self, query: GetAgentDiagramElementQuery) -> DiagramElementDetailDto | None:
        self.access_policy.ensure_read_access(query.project_id, query.user_id)
        return self.reader.get_element(
            project_id=query.project_id,
            element_type=query.element_type,
            element_id=query.element_id,
        )
