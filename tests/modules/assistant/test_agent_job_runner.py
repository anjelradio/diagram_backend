import anyio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.services import agent_job_runner as runner_module
from app.modules.assistant.infrastructure.services.agent_job_runner import AgentJobRunner
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


@pytest.mark.anyio
async def test_job_runs_independently_after_acceptance_and_persists_terminal(
    monkeypatch, test_engine, test_project: ProjectModel
):
    message = AgentMessage.register(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        prompt="Create a Product class",
    )
    with Session(test_engine) as session:
        SQLModelAgentMessageRepository(session).save_new(message)
        session.commit()

    started = anyio.Event()
    finish = anyio.Event()
    runner = AgentJobRunner(
        session_factory=lambda: Session(test_engine), worker_id="test-worker"
    )
    runner.POLL_SECONDS = 0.01
    runner.HEARTBEAT_SECONDS = 0.02

    class FakeProcess:
        async def execute(self, *, message_id, project_id, user_id):
            started.set()
            await finish.wait()
            with Session(test_engine) as session:
                repository = SQLModelAgentMessageRepository(
                    session, worker_id=runner.worker_id
                )
                current = repository.find_by_id(message_id)
                assert current is not None
                current.complete("Creé Producto.")
                assert repository.save_terminal(current)
                session.commit()

    monkeypatch.setattr(
        runner_module,
        "build_process_agent_message_use_case",
        lambda **_kwargs: FakeProcess(),
    )

    await runner.start()
    runner.notify(message.id)
    try:
        with anyio.fail_after(2):
            await started.wait()
        # La petición puede terminar/cerrarse mientras el job sigue activo.
        with Session(test_engine) as session:
            active = SQLModelAgentMessageRepository(session).find_by_id(message.id)
            assert active is not None
            assert active.status is AgentMessageStatus.RUNNING
        finish.set()
        with anyio.fail_after(2):
            while True:
                with Session(test_engine) as session:
                    persisted = SQLModelAgentMessageRepository(session).find_by_id(
                        message.id
                    )
                if persisted and persisted.status is AgentMessageStatus.COMPLETED:
                    break
                await anyio.sleep(0.01)
        assert persisted.response_markdown == "Creé Producto."
    finally:
        finish.set()
        await runner.stop()


def test_recovery_fails_closed_when_a_mutation_ledger_exists():
    assert runner_module._has_unreplayable_mutation_state(
        {"operation_ledger": [{"operation_id": "op-1", "status": "applied"}]}
    )
    assert not runner_module._has_unreplayable_mutation_state(
        {"operation_ledger": []}
    )
    assert not runner_module._has_unreplayable_mutation_state(None)


@pytest.mark.anyio
async def test_worker_stops_active_processing_and_persists_cancelled(
    monkeypatch, test_engine, test_project: ProjectModel
):
    message = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Do work"
    )
    with Session(test_engine) as session:
        repository = SQLModelAgentMessageRepository(session)
        repository.save_new(message)
        session.commit()
        claimed = repository.claim_next(
            worker_id="cancel-worker",
            now=datetime.now(timezone.utc),
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=2),
        )
        session.commit()

    assert claimed is not None
    runner = AgentJobRunner(
        session_factory=lambda: Session(test_engine), worker_id="cancel-worker"
    )
    runner.HEARTBEAT_SECONDS = 0.01
    stop_events = []

    class FakeProcess:
        async def execute(self, **_kwargs):
            await anyio.sleep_forever()

    monkeypatch.setattr(
        runner_module,
        "build_process_agent_message_use_case",
        lambda **kwargs: (stop_events.append(kwargs["activity_stopped"]) or FakeProcess()),
    )
    with Session(test_engine) as session:
        SQLModelAgentMessageRepository(session).request_cancel(
            message_id=message.id,
            project_id=message.project_id,
            user_id=message.user_id,
            now=datetime.now(timezone.utc),
        )
        session.commit()

    await runner._run_claimed(claimed)

    with Session(test_engine) as session:
        cancelled = SQLModelAgentMessageRepository(session).find_by_id(message.id)
    assert cancelled is not None
    assert cancelled.status is AgentMessageStatus.CANCELLED
    assert cancelled.response_markdown
    assert stop_events and stop_events[0].is_set()


@pytest.mark.anyio
async def test_lost_lease_stops_activity_callback_and_cancels_process(monkeypatch, test_project):
    message = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Do work"
    )
    runner = AgentJobRunner(worker_id="lease-worker")
    stop_events = []
    cancelled = anyio.Event()

    class FakeProcess:
        async def execute(self, **_kwargs):
            try:
                await anyio.sleep_forever()
            finally:
                cancelled.set()

    monkeypatch.setattr(
        runner_module,
        "build_process_agent_message_use_case",
        lambda **kwargs: (stop_events.append(kwargs["activity_stopped"]) or FakeProcess()),
    )

    async def lease_lost(_message_id, _process_task):
        await anyio.sleep(0)
        return "lease_lost"

    monkeypatch.setattr(runner, "_monitor", lease_lost)
    await runner._run_claimed(message)

    assert stop_events and stop_events[0].is_set()
    assert cancelled.is_set()

