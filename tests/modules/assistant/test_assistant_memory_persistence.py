from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_user_memory_repository import (
    SQLModelAgentUserMemoryRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def test_memory_is_created_and_updated_for_one_user_project_pair(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentUserMemoryRepository(session)
    memory = AgentUserMemory.create(
        user_id="user_owner", project_id=test_project.id, summary_context="## Goal\nERD"
    )
    repository.save(memory)
    session.commit()

    memory.append_interaction("Add a member role", "A member has one project role.")
    repository.save(memory)
    session.commit()

    loaded = repository.find_active(user_id="user_owner", project_id=test_project.id)
    assert loaded is not None
    assert loaded.id == memory.id
    assert "## Interacciones recientes" in loaded.summary_context
    assert "A member has one project role." in loaded.summary_context


def test_memory_and_completed_message_changes_roll_back_atomically(
    session: Session, test_project: ProjectModel
):
    message_repository = SQLModelAgentMessageRepository(session)
    memory_repository = SQLModelAgentUserMemoryRepository(session)
    message = AgentMessage.register(
        id=uuid4(), project_id=test_project.id, user_id="user_owner", prompt="Explain"
    )
    memory = AgentUserMemory.create(
        user_id="user_owner", project_id=test_project.id, summary_context="old memory"
    )
    message_repository.save_new(message)
    memory_repository.save(memory)
    session.commit()

    message.complete("new answer")
    memory.update_summary_context("new memory")
    assert message_repository.save_terminal(message)

    def fail_commit(_session):
        raise RuntimeError("database unavailable")

    event.listen(session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError):
            session.commit()
    finally:
        event.remove(session, "before_commit", fail_commit)
        session.rollback()

    persisted_message = session.get(AgentMessageModel, message.id)
    persisted_memory = memory_repository.find_active(
        user_id="user_owner", project_id=test_project.id
    )
    assert persisted_message is not None
    assert persisted_message.status == "running"
    assert persisted_memory is not None
    assert persisted_memory.summary_context == "old memory"


    assert "https://res.cloudinary.com/private/image.png" not in memory.summary_context


def test_memory_isolation_and_applied_operations_persisted(
    session: Session, test_project: ProjectModel
):
    repository = SQLModelAgentUserMemoryRepository(session)
    other_project = ProjectModel(
        id=uuid4(),
        name="Other Project",
        owner_id="user_owner",
    )
    session.add(other_project)
    session.commit()

    user_a = "user_a"
    user_b = "user_b"

    # 1. Crear memoria para (test_project.id, user_a)
    mem_a = AgentUserMemory.create(
        user_id=user_a,
        project_id=test_project.id,
        summary_context="## Memoria de Usuario A en Proyecto 1",
    )
    repository.save(mem_a)

    # 2. Crear memoria para (other_project.id, user_b)
    mem_b = AgentUserMemory.create(
        user_id=user_b,
        project_id=other_project.id,
        summary_context="## Memoria de Usuario B en Proyecto 2",
    )
    repository.save(mem_b)
    session.commit()

    # 3. Verificar aislamiento estricto (project_id, user_id)
    assert repository.find_active(user_id=user_a, project_id=test_project.id) is not None
    assert repository.find_active(user_id=user_b, project_id=other_project.id) is not None
    # Cruces deben retornar None
    assert repository.find_active(user_id=user_b, project_id=test_project.id) is None
    assert repository.find_active(user_id=user_a, project_id=other_project.id) is None

    # 4. Solo operaciones applied deben persistirse
    mem_a.append_interaction(
        "Crea Factura y elimina Usuario",
        "Factura creada; Usuario no pudo eliminarse.",
        confirmed_operations=[
            {"status": "applied", "action_kind": "CREATE_CLASS", "entity_refs": [{"type": "class", "id": "factura-id"}]},
            {"status": "failed", "action_kind": "DELETE_CLASS", "entity_refs": [{"type": "class", "id": "usuario-id"}]},
        ],
    )
    repository.save(mem_a)
    session.commit()

    reloaded_a = repository.find_active(user_id=user_a, project_id=test_project.id)
    assert reloaded_a is not None
    assert "factura-id" in reloaded_a.summary_context
    assert "usuario-id" not in reloaded_a.summary_context


@pytest.mark.anyio
async def test_memory_provider_failure_after_confirmed_execution_preserves_terminal_message_and_old_memory(
    session: Session, test_project: ProjectModel
):
    from app.core.dependencies import get_event_bus
    from app.modules.assistant.application.ports.providers.ai_provider import (
        AiProvider,
        AiResult,
    )
    from app.modules.assistant.application.services.context_builder import (
        ContextBuilder,
    )
    from app.modules.assistant.application.services.memory_updater import (
        MemoryUpdater,
    )
    from app.modules.assistant.application.services.token_estimator import (
        TokenEstimator,
    )
    from app.modules.assistant.application.use_cases.process_agent_message import (
        ProcessAgentMessageUseCase,
    )
    from app.modules.collaboration.application.services.project_access_policy import (
        ProjectAccessPolicy,
    )
    from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
        SQLModelProjectMemberRepository,
    )
    from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
        SQLModelProjectRepository,
    )
    from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork

    message_repo = SQLModelAgentMessageRepository(session)
    memory_repo = SQLModelAgentUserMemoryRepository(session)
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    uow = SqlModelUnitOfWork(session, get_event_bus())

    user_id = "user_owner"
    initial_summary = (
        "## Objetivos activos\n- Mantener este resumen válido\n\n"
        "## Preferencias del usuario\n- Formato conciso\n\n"
        "## Decisiones y restricciones vigentes\n\n"
        "## Resultados confirmados relevantes\n\n"
        "## Pendientes o dudas"
    )
    existing_memory = AgentUserMemory.create(
        user_id=user_id,
        project_id=test_project.id,
        summary_context=initial_summary,
    )
    memory_repo.save(existing_memory)
    session.commit()

    message = AgentMessage.register(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_id,
        prompt="Añade un cambio confirmado al diagrama",
    )
    message_repo.save_new(message)
    session.commit()

    class FailingMemoryAiProvider(AiProvider):
        async def complete(self, request):
            if request is not None and request.purpose == "memory_update":
                raise RuntimeError("Compaction LLM service down")
            return AiResult(
                text="Operación completada con éxito.",
                model_role=request.model_role if request else None,
                model="test-ai",
                completed=True,
                metadata={
                    "status": "completed",
                    "operation_ledger": [
                        {
                            "operation_id": "op-test-1",
                            "action_kind": "CREATE_CLASS",
                            "status": "applied",
                            "entity_refs": [{"type": "class", "id": "class-persisted-1"}],
                        }
                    ],
                },
            )

    provider = FailingMemoryAiProvider()
    token_estimator = TokenEstimator()
    memory_updater = MemoryUpdater(provider, token_estimator, max_tokens=7000)

    class StubOrchestrator:
        async def respond_with_progress(self, context, on_progress, on_activity):
            return await provider.complete(None)

    use_case = ProcessAgentMessageUseCase(
        message_repository=message_repo,
        memory_repository=memory_repo,
        project_access_policy=access_policy,
        context_builder=ContextBuilder(memory_repo, token_estimator),
        orchestrator=StubOrchestrator(),
        uow=uow,
        memory_updater=memory_updater,
    )

    result = await use_case.execute(
        message_id=message.id,
        project_id=test_project.id,
        user_id=user_id,
    )

    # 1. El mensaje terminal persiste como completed
    assert result.status == "completed"
    persisted_message = session.get(AgentMessageModel, message.id)
    assert persisted_message is not None
    assert persisted_message.status == "completed"

    # 2. La memoria anterior NO se perdió ni se corrompió
    reloaded_memory = memory_repo.find_active(user_id=user_id, project_id=test_project.id)
    assert reloaded_memory is not None
    assert reloaded_memory.summary_context == initial_summary


@pytest.mark.anyio
async def test_message_execution_produces_zero_writes_to_user_memory(
    session: Session, test_project: ProjectModel
):
    """El procesamiento de un mensaje completado no escribe ni modifica registros en agent_user_memories."""
    from sqlmodel import select
    from app.modules.assistant.application.ports.providers.ai_provider import (
        AiResult,
        ModelRole,
    )
    from app.modules.assistant.infrastructure.services.agent_runtime_factory import (
        build_process_agent_message_use_case,
    )
    from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
        AgentUserMemoryModel,
    )

    initial_memories = session.exec(select(AgentUserMemoryModel)).all()
    initial_count = len(initial_memories)

    user_id = test_project.owner_id
    worker_id = "worker_test_mem_bounds"
    message_repo = SQLModelAgentMessageRepository(session)
    message = AgentMessage.register(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_id,
        prompt="Crea la clase Factura con el atributo total",
    )
    message_repo.save_new(message)
    msg_model = session.get(AgentMessageModel, message.id)
    msg_model.lease_owner = worker_id
    session.add(msg_model)
    session.commit()

    use_case = build_process_agent_message_use_case(
        session=session,
        project_id=test_project.id,
        user_id=user_id,
        message_id=message.id,
        worker_id=worker_id,
    )

    class MockOrchestrator:
        async def respond_with_progress(self, context, on_progress, on_activity):
            return AiResult(
                text="Clase Factura creada exitosamente.",
                model_role=ModelRole.MAIN,
                model="test-ai",
                completed=True,
                metadata={
                    "status": "completed",
                    "operation_ledger": [
                        {
                            "operation_id": "op-test-1",
                            "action_kind": "CREATE_CLASS",
                            "status": "applied",
                            "entity_refs": [{"type": "class", "id": "factura-id"}],
                        }
                    ],
                },
            )

    use_case.orchestrator = MockOrchestrator()

    result = await use_case.execute(
        message_id=message.id,
        project_id=test_project.id,
        user_id=user_id,
    )

    assert result.status == "completed"

    memories_after = session.exec(
        select(AgentUserMemoryModel).where(
            AgentUserMemoryModel.project_id == test_project.id,
            AgentUserMemoryModel.user_id == user_id,
        )
    ).all()
    assert len(memories_after) == 0
    assert len(session.exec(select(AgentUserMemoryModel)).all()) == initial_count
