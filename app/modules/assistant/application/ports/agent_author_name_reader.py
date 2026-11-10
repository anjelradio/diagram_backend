from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AgentAuthorProfile:
    name: str | None
    avatar_url: str | None


class AgentAuthorNameReader(Protocol):
    """Resuelve nombres de autor en una consulta por lote, sin N+1."""

    def find_names(self, user_ids: set[str]) -> dict[str, str]:
        """Devuelve los nombres disponibles; IDs ausentes se presentan como fallback."""
        ...

    def find_profiles(self, user_ids: set[str]) -> dict[str, AgentAuthorProfile]:
        """Devuelve nombre e imagen de perfil en una única consulta para el lote."""
        ...

