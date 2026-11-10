from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)


class AgentUserMemoryMapper:
    """Convierte memorias entre dominio y SQLModel."""

    @staticmethod
    def to_model(entity: AgentUserMemory) -> AgentUserMemoryModel:
        return AgentUserMemoryModel(
            id=entity.id,
            user_id=entity.user_id,
            project_id=entity.project_id,
            summary_context=entity.summary_context,
        )

    @staticmethod
    def to_domain(model: AgentUserMemoryModel) -> AgentUserMemory:
        return AgentUserMemory(
            id=model.id,
            user_id=model.user_id,
            project_id=model.project_id,
            summary_context=model.summary_context,
        )
