from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_activity_state import (
    AgentActivityState,
)
from app.modules.assistant.infrastructure.persistence.models.agent_activity_model import (
    AgentActivityModel,
)


class AgentActivityMapper:
    """Mapeador bidireccional entre la entidad de dominio AgentActivity y AgentActivityModel."""

    @staticmethod
    def to_domain(model: AgentActivityModel) -> AgentActivity:
        return AgentActivity(
            id=model.id,
            project_id=model.project_id,
            transcription=model.transcription,
            resume=model.resume,
            image_url=model.image_url,
            state=AgentActivityState(model.state),
            created_date=model.created_date,
        )

    @staticmethod
    def to_model(activity: AgentActivity) -> AgentActivityModel:
        return AgentActivityModel(
            id=activity.id,
            project_id=activity.project_id,
            transcription=activity.transcription,
            resume=activity.resume,
            image_url=activity.image_url,
            state=activity.state.value,
        )
