from uuid import UUID
from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_activity_state import (
    AgentActivityState,
)
from app.modules.assistant.domain.repositories.agent_activity_repository import (
    AgentActivityRepository,
)
from app.modules.assistant.infrastructure.persistence.mappers.agent_activity_mapper import (
    AgentActivityMapper,
)
from app.modules.assistant.infrastructure.persistence.models.agent_activity_model import (
    AgentActivityModel,
)
from app.shared.infrastructure.db.base_model import utc_now


class SQLModelAgentActivityRepository(AgentActivityRepository):
    """Implementación en SQLModel de AgentActivityRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, activity: AgentActivity) -> None:
        model = self.session.get(AgentActivityModel, activity.id)
        if model is None:
            new_model = AgentActivityMapper.to_model(activity)
            self.session.add(new_model)
        else:
            model.transcription = activity.transcription
            model.resume = activity.resume
            model.image_url = activity.image_url
            model.state = activity.state.value
            model.modified_date = utc_now()
            self.session.add(model)

    def find_by_id(self, activity_id: UUID) -> AgentActivity | None:
        statement = select(AgentActivityModel).where(
            AgentActivityModel.id == activity_id,
            AgentActivityModel.deleted_date.is_(None),
        )
        model = self.session.exec(statement).first()
        if model is None:
            return None
        return AgentActivityMapper.to_domain(model)

    def find_active_by_project_id(self, project_id: UUID) -> AgentActivity | None:
        statement = (
            select(AgentActivityModel)
            .where(
                AgentActivityModel.project_id == project_id,
                AgentActivityModel.state == AgentActivityState.IN_PROGRESS.value,
                AgentActivityModel.deleted_date.is_(None),
            )
            .order_by(AgentActivityModel.created_date.desc())
        )
        model = self.session.exec(statement).first()
        if model is None:
            return None
        return AgentActivityMapper.to_domain(model)

    def find_all_by_project_id(self, project_id: UUID) -> list[AgentActivity]:
        statement = (
            select(AgentActivityModel)
            .where(
                AgentActivityModel.project_id == project_id,
                AgentActivityModel.deleted_date.is_(None),
            )
            .order_by(AgentActivityModel.created_date.desc())
        )
        models = self.session.exec(statement).all()
        return [AgentActivityMapper.to_domain(m) for m in models]
