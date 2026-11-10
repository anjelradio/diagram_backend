"""Puerto para búsquedas y detalles acotados del diagrama para herramientas."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DiagramElementReferenceDto:
    """Referencia pequeña a un elemento visible del diagrama."""

    element_type: str
    id: UUID
    name: str
    owner_class_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DiagramElementSearchDto:
    """Página acotada de elementos que coinciden con una búsqueda."""

    items: tuple[DiagramElementReferenceDto, ...]
    has_more: bool
    next_offset: int | None
    ambiguous_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagramElementDetailDto:
    """Detalle acotado, serializable, de clase, atributo o relación."""

    element_type: str
    id: UUID
    name: str
    details: dict[str, Any]


class AgentDiagramReader(ABC):
    """Consultas acotadas bajo el alcance de un proyecto."""

    @abstractmethod
    def search_elements(
        self,
        *,
        project_id: UUID,
        query: str,
        types: tuple[str, ...],
        limit: int,
        offset: int,
    ) -> DiagramElementSearchDto:
        """Busca por nombre sin construir el snapshot completo del proyecto."""

    @abstractmethod
    def get_element(
        self, *, project_id: UUID, element_type: str, element_id: UUID
    ) -> DiagramElementDetailDto | None:
        """Obtiene un elemento y sus relaciones incidentes únicamente."""
