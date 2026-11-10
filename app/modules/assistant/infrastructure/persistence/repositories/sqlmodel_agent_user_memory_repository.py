from uuid import UUID

from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.domain.repositories.agent_user_memory_repository import (
    AgentUserMemoryRepository,
)
from app.modules.assistant.infrastructure.persistence.mappers.agent_user_memory_mapper import (
    AgentUserMemoryMapper,
)
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)


class SQLModelAgentUserMemoryRepository(AgentUserMemoryRepository):
    """Persistencia SQLModel de memorias activas."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_active(self, *, user_id: str, project_id: UUID) -> AgentUserMemory | None:
        statement = select(AgentUserMemoryModel).where(
            AgentUserMemoryModel.user_id == user_id,
            AgentUserMemoryModel.project_id == project_id,
            AgentUserMemoryModel.deleted_date.is_(None),
        )
        record = self.session.exec(statement).first()
        return AgentUserMemoryMapper.to_domain(record) if record is not None else None

    def save(self, memory: AgentUserMemory) -> None:
        statement = select(AgentUserMemoryModel).where(
            AgentUserMemoryModel.id == memory.id,
            AgentUserMemoryModel.deleted_date.is_(None),
        )
        record = self.session.exec(statement).first()
        if record is None:
            self.session.add(AgentUserMemoryMapper.to_model(memory))
            return
        record.user_id = memory.user_id
        record.project_id = memory.project_id
        record.summary_context = memory.summary_context
        self.session.add(record)
