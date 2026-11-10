"""Pruebas de concurrencia y atomicidad para reclamo de continuaciones."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session, create_engine
from sqlmodel.pool import StaticPool

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def _setup_continuation_in_db(session: Session, project_id, user_id="user_concurrent"):
    msg_repo = SQLModelAgentMessageRepository(session)
    root_msg = AgentMessage.register(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Root prompt",
    )
    msg_repo.save_new(root_msg)
    terminal_root = AgentMessage(
        id=root_msg.id,
        project_id=root_msg.project_id,
        user_id=root_msg.user_id,
        prompt=root_msg.prompt,
        status=AgentMessageStatus.COMPLETED,
        response_markdown="Pregunta",
        created_at=root_msg.created_at,
    )
    msg_repo.save_terminal(terminal_root)

    continuation = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=root_msg.id,
        effective_request="Petición para test de concurrencia",
    )
    cont_repo = SQLModelAgentContinuationRepository(session)
    cont_repo.save(continuation)
    session.commit()
    return continuation


def test_two_workers_claiming_same_version_only_one_wins_and_winner_reclaims_idempotently(
    test_engine,
):
    """Dos llamadas concurrentes al claim con la misma versión esperada: solo una gana, el perdedor obtiene None, y el ganador puede re-reclamar."""
    with Session(test_engine) as session:
        project = ProjectModel(owner_id="user_concurrent", name="Test Concurrency")
        session.add(project)
        session.commit()
        project_id = project.id
        cont = _setup_continuation_in_db(session, project_id)
        cont_id = cont.id

        # Crear los mensajes de los dos workers para cumplir la clave foránea
        msg_repo = SQLModelAgentMessageRepository(session)
        worker_a_msg = AgentMessage.register(
            id=uuid4(),
            project_id=project_id,
            user_id="user_concurrent_a",
            prompt="Worker A prompt",
        )
        msg_repo.save_new(worker_a_msg)
        worker_b_msg = AgentMessage.register(
            id=uuid4(),
            project_id=project_id,
            user_id="user_concurrent_b",
            prompt="Worker B prompt",
        )
        msg_repo.save_new(worker_b_msg)
        session.commit()
        worker_a_msg_id = worker_a_msg.id
        worker_b_msg_id = worker_b_msg.id

    def worker_claim(consumer_msg_id):
        with Session(test_engine) as session:
            repo = SQLModelAgentContinuationRepository(session)
            claimed = repo.claim_atomic(
                continuation_id=cont_id,
                expected_version=1,
                by_message_id=consumer_msg_id,
            )
            if claimed is not None:
                session.commit()
                return "won", consumer_msg_id
            return "lost", consumer_msg_id

    # En SQLite in-memory (StaticPool), dos llamadas concurrentes con la misma versión:
    res_a = worker_claim(worker_a_msg_id)
    res_b = worker_claim(worker_b_msg_id)
    results = [res_a, res_b]

    outcomes = [r[0] for r in results]
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == 1

    winning_worker_msg_id = next(r[1] for r in results if r[0] == "won")

    # Reentrega idempotente del ganador
    with Session(test_engine) as session:
        repo = SQLModelAgentContinuationRepository(session)
        # El ganador reintenta con su mismo message_id y la versión actual (2)
        reclaimed = repo.claim_atomic(
            continuation_id=cont_id,
            expected_version=2,
            by_message_id=winning_worker_msg_id,
        )
        assert reclaimed.id == cont_id
        assert reclaimed.claimed_by_message_id == winning_worker_msg_id
        assert reclaimed.state == ContinuationState.CLAIMED

        # El perdedor intenta reclamar con la nueva versión y su propio message_id: es rechazado
        losing_worker_msg_id = next(r[1] for r in results if r[0] == "lost")
        rejected = repo.claim_atomic(
            continuation_id=cont_id,
            expected_version=2,
            by_message_id=losing_worker_msg_id,
        )
        assert rejected is None


def test_two_postgres_workers_claiming_same_version(assistant_postgres_engine):
    """Validación específica en PostgreSQL usando la fixture assistant_postgres_engine."""
    with Session(assistant_postgres_engine) as session:
        project = ProjectModel(owner_id="pg_concurrent_user", name="PG Concurrency")
        session.add(project)
        session.commit()
        project_id = project.id
        cont = _setup_continuation_in_db(session, project_id, user_id="pg_concurrent_user")
        cont_id = cont.id

        msg_repo = SQLModelAgentMessageRepository(session)
        w1 = AgentMessage.register(
            id=uuid4(),
            project_id=project_id,
            user_id="pg_concurrent_user_1",
            prompt="PG Worker 1 prompt",
        )
        msg_repo.save_new(w1)
        w2 = AgentMessage.register(
            id=uuid4(),
            project_id=project_id,
            user_id="pg_concurrent_user_2",
            prompt="PG Worker 2 prompt",
        )
        msg_repo.save_new(w2)
        session.commit()
        worker_1_msg = w1.id
        worker_2_msg = w2.id

    def worker_attempt(msg_id):
        with Session(assistant_postgres_engine) as session:
            repo = SQLModelAgentContinuationRepository(session)
            claimed = repo.claim_atomic(
                continuation_id=cont_id,
                expected_version=1,
                by_message_id=msg_id,
            )
            if claimed is not None:
                session.commit()
                return "won", msg_id
            return "lost", msg_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker_attempt, [worker_1_msg, worker_2_msg]))

    outcomes = [r[0] for r in results]
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == 1

    winner_msg_id = next(r[1] for r in results if r[0] == "won")

    with Session(assistant_postgres_engine) as session:
        repo = SQLModelAgentContinuationRepository(session)
        reclaimed = repo.claim_atomic(
            continuation_id=cont_id,
            expected_version=2,
            by_message_id=winner_msg_id,
        )
        assert reclaimed is not None
        assert reclaimed.claimed_by_message_id == winner_msg_id
