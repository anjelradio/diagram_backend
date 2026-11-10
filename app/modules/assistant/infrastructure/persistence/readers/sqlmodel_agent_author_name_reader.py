from sqlmodel import Session, select

from app.modules.assistant.application.ports.agent_author_name_reader import (
    AgentAuthorProfile,
    AgentAuthorNameReader,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


class SQLModelAgentAuthorNameReader(AgentAuthorNameReader):
    """Obtiene nombres de autores en una sola consulta por página."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_names(self, user_ids: set[str]) -> dict[str, str]:
        return {
            user_id: profile.name
            for user_id, profile in self.find_profiles(user_ids).items()
            if profile.name
        }

    def find_profiles(self, user_ids: set[str]) -> dict[str, AgentAuthorProfile]:
        if not user_ids:
            return {}
        rows = self.session.exec(
            select(BetterAuthUser.id, BetterAuthUser.name, BetterAuthUser.image).where(
                BetterAuthUser.id.in_(user_ids)
            )
        ).all()
        return {
            user_id: AgentAuthorProfile(name=name or None, avatar_url=image)
            for user_id, name, image in rows
        }

