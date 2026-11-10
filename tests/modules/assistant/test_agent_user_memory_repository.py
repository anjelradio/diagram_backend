from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_user_memory_repository import (
    SQLModelAgentUserMemoryRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def test_memory_persists_and_reconstructs(session: Session, test_project: ProjectModel):
    repository = SQLModelAgentUserMemoryRepository(session)
    memory = AgentUserMemory.create(
        user_id="user_owner", project_id=test_project.id, summary_context="Summary"
    )
    repository.save(memory)
    session.commit()

    loaded = repository.find_active(user_id="user_owner", project_id=test_project.id)
    assert loaded is not None
    assert loaded.id == memory.id
    assert loaded.summary_context == "Summary"


def test_only_one_active_memory_per_user_project(
    session: Session, test_project: ProjectModel
):
    session.add(
        AgentUserMemoryModel(
            user_id="user_owner", project_id=test_project.id, summary_context="one"
        )
    )
    session.commit()
    session.add(
        AgentUserMemoryModel(
            user_id="user_owner", project_id=test_project.id, summary_context="two"
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    else:
        raise AssertionError("Expected the partial unique index to reject a duplicate")
