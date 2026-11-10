from uuid import uuid4

from sqlmodel import Session, select

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def test_soft_deleted_running_message_releases_slot(session: Session, test_project: ProjectModel):
    running = AgentMessageModel(
        project_id=test_project.id,
        user_id="user_owner",
        prompt="one",
        status="running",
    )
    session.add(running)
    session.commit()
    running.soft_delete()
    session.add(running)
    session.commit()

    message = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="two"
    )
    SQLModelAgentMessageRepository(session).save_new(message)
    session.commit()

    active = session.exec(
        select(AgentMessageModel).where(AgentMessageModel.deleted_date.is_(None))
    ).all()
    assert [record.status for record in active] == ["running"]


def test_terminal_failed_message_releases_slot_for_next_message_in_queue(session: Session, test_project: ProjectModel):
    # T014: Un mensaje terminado por fallo de dominio libera su slot y lease,
    # permitiendo que el siguiente mensaje en cola sea reclamado y procesado limpiamente.
    from datetime import datetime, timedelta, timezone

    repo = SQLModelAgentMessageRepository(session)
    now = datetime.now(timezone.utc)

    # Mensaje 1 activo (running)
    msg1 = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Mensaje 1 que fallará"
    )
    repo.save_new(msg1)
    session.commit()

    # Reclamar mensaje 1
    claimed1 = repo.claim_next(worker_id="w1", now=now, lease_until=now + timedelta(seconds=60))
    session.commit()
    assert claimed1 is not None and claimed1.id == msg1.id

    # Mensaje 1 falla por conflicto de dominio terminal y se persiste como terminal
    claimed1.fail("No se pudo completar la solicitud porque la clase ya no está disponible.")
    saved_terminal = repo.save_terminal(claimed1)
    session.commit()
    assert saved_terminal is True

    # El slot para user_owner está ahora libre: Mensaje 2 se puede registrar y reclamar inmediatamente
    msg2 = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Mensaje 2 independiente"
    )
    repo.save_new(msg2)
    session.commit()

    claimed2 = repo.claim_next(worker_id="w1", now=now, lease_until=now + timedelta(seconds=60))
    session.commit()
    assert claimed2 is not None
    assert claimed2.id == msg2.id
    assert claimed2.status.value == "running"
    assert claimed2.prompt == "Mensaje 2 independiente"


def test_terminal_partial_message_releases_slot_for_next_message_in_queue(session: Session, test_project: ProjectModel):
    # T009 [US1]: Un mensaje en estado partial es terminal, libera su slot y lease,
    # y permite que el siguiente mensaje sea registrado y reclamado.
    from datetime import datetime, timedelta, timezone

    repo = SQLModelAgentMessageRepository(session)
    now = datetime.now(timezone.utc)

    msg1 = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Mensaje 1 parcial"
    )
    repo.save_new(msg1)
    session.commit()

    claimed1 = repo.claim_next(worker_id="w1", now=now, lease_until=now + timedelta(seconds=60))
    session.commit()
    assert claimed1 is not None and claimed1.id == msg1.id

    claimed1.partial("Se completó 1 tarea y 1 quedó pendiente.")
    saved_terminal = repo.save_terminal(claimed1)
    session.commit()
    assert saved_terminal is True

    # El mensaje ya no está activo
    active = repo.get_active_for_user(project_id=test_project.id, user_id="user_owner")
    assert active is None

    # El siguiente mensaje puede registrarse y reclamarse
    msg2 = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Mensaje 2"
    )
    repo.save_new(msg2)
    session.commit()

    claimed2 = repo.claim_next(worker_id="w1", now=now, lease_until=now + timedelta(seconds=60))
    session.commit()
    assert claimed2 is not None
    assert claimed2.id == msg2.id
    assert claimed2.status.value == "running"


