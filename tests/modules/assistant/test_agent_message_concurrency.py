from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.exceptions import AgentAlreadyActiveException
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def test_twenty_independent_postgres_sessions_make_one_running(assistant_postgres_engine):
    with Session(assistant_postgres_engine) as session:
        project = ProjectModel(owner_id="concurrent-user", name="Concurrent")
        session.add(project)
        session.commit()
        project_id = project.id

    def create_message(_):
        with Session(assistant_postgres_engine) as session:
            message = AgentMessage.register(
                id=uuid4(),
                project_id=project_id,
                user_id="concurrent-user",
                prompt="Concurrent message",
            )
            try:
                SQLModelAgentMessageRepository(session).save_new(message)
            except AgentAlreadyActiveException:
                session.rollback()
                return "rejected"
            session.commit()
            return message.status.value

    with ThreadPoolExecutor(max_workers=20) as executor:
        statuses = list(executor.map(create_message, range(20)))

    assert statuses.count("running") == 1
    assert statuses.count("rejected") == 19
    with Session(assistant_postgres_engine) as session:
        running = session.exec(
            select(AgentMessageModel).where(
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == "concurrent-user",
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
            )
        ).all()
    assert len(running) == 1
