from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)
from app.modules.assistant.infrastructure.services import agent_runtime_factory
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from tests.modules.assistant.agent_test_helpers import process_and_fetch_message


class CompactionProvider:
    def __init__(self, session: Session, *, fail_compaction=False):
        self.session = session
        self.fail_compaction = fail_compaction
        self.calls = []
        self.main_memory_at_call = None

    async def complete(self, request):
        self.calls.append(request)
        if request.model_role is ModelRole.COMPACTION:
            if self.fail_compaction:
                raise RuntimeError("private compaction failure")
            return AiResult(
                text="## Contexto\nEl proyecto usa roles de miembros.",
                model_role=request.model_role,
                model="compact",
            )
        if request.model_role is ModelRole.MAIN:
            memory = self.session.exec(select(AgentUserMemoryModel)).first()
            self.main_memory_at_call = memory.summary_context if memory is not None else None
            return AiResult(
                text="La respuesta utiliza la memoria compactada.",
                model_role=request.model_role,
                model="main",
            )
        raise AssertionError(f"unexpected provider role: {request.model_role}")


def _post(client, project_id, prompt="Summarize the project"):
    return client.post(
        f"/api/projects/{project_id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, prompt),
        },
    )


def _seed_memory(session: Session, user_id: str, project_id, text: str):
    memory = AgentUserMemory.create(
        user_id=user_id, project_id=project_id, summary_context=text
    )
    session.add(
        AgentUserMemoryModel(
            id=memory.id,
            user_id=memory.user_id,
            project_id=memory.project_id,
            summary_context=memory.summary_context,
        )
    )
    session.commit()
    return memory


def test_compacts_at_threshold_persists_before_main_and_returns_completed(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Con la compactación retirada en T022, un mensaje con memoria previa no invoca compactación y completa normalmente."""
    original = "m" * 18_898
    provider = CompactionProvider(session)
    app.dependency_overrides[get_current_user] = lambda: owner_user
    _seed_memory(session, owner_user.user_id, test_project.id, original)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.model_role for request in provider.calls if request.purpose != "memory_update"] == [ModelRole.MAIN]
    saved_memory = session.exec(select(AgentUserMemoryModel)).first()
    assert saved_memory.summary_context == original
    message = session.get(AgentMessageModel, UUID(response.json()["message_id"]))
    assert message is not None and message.status == "completed"


def test_memory_just_below_threshold_skips_compaction(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    provider = CompactionProvider(session)
    app.dependency_overrides[get_current_user] = lambda: owner_user
    _seed_memory(session, owner_user.user_id, test_project.id, "m" * 18_895)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.model_role for request in provider.calls if request.purpose != "memory_update"] == [ModelRole.MAIN]


def test_compaction_failure_preserves_old_memory_and_skips_main(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """Al estar la compactación retirada, el proveedor nunca recibe ModelRole.COMPACTION y la memoria previa se preserva intacta."""
    original = "m" * 18_898
    provider = CompactionProvider(session, fail_compaction=True)
    app.dependency_overrides[get_current_user] = lambda: owner_user
    _seed_memory(session, owner_user.user_id, test_project.id, original)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.model_role for request in provider.calls] == [ModelRole.MAIN]
    saved_memory = session.exec(select(AgentUserMemoryModel)).first()
    assert saved_memory.summary_context == original

