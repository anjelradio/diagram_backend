from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    AiToolCall,
)
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.services import agent_runtime_factory
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from sqlmodel import select
from tests.modules.assistant.agent_test_helpers import process_and_fetch_message


class FakeAiProvider:
    def __init__(self, *, should_fail=False):
        self.calls = []
        self.should_fail = should_fail

    async def complete(self, request):
        self.calls.append(request)
        if self.should_fail:
            raise RuntimeError("private provider error")
        return AiResult(
            text="## Answer\nThe diagram has two entities.",
            model_role=request.model_role,
            model="fake-qwen",
        )


def _post(client, project_id, message_id=None, prompt="Describe this project"):
    return client.post(
        f"/api/projects/{project_id}/assistant/messages",
        files={
            "message_id": (None, str(message_id or uuid4())),
            "prompt": (None, prompt),
        },
    )


def test_text_post_returns_completed_response_and_persists_markdown(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    provider = FakeAiProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)
    message_id = uuid4()

    accepted = _post(client, test_project.id, message_id)
    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["response_markdown"] == "## Answer\nThe diagram has two entities."
    assert len([c for c in provider.calls if c.purpose != "memory_update"]) == 1
    persisted = session.get(AgentMessageModel, message_id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.response_markdown == response.json()["response_markdown"]


def test_text_post_executes_registered_diagram_tool_and_persists_confirmed_plan(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    class ToolCallingProvider:
        def __init__(self):
            self.calls = []

        async def complete(self, request):
            self.calls.append(request)
            if len(self.calls) == 1:
                return AiResult(
                    text="",
                    model_role=request.model_role,
                    model="fake-qwen",
                    tool_calls=(
                        AiToolCall(
                            id="create-product-op",
                            name="apply_diagram_changes",
                            arguments={
                                "actions": [
                                    {
                                        "operation_id": "create-product",
                                        "kind": "CREATE_CLASS",
                                        "name": "Producto",
                                    }
                                ]
                            },
                        ),
                    ),
                )
            return AiResult(
                text="Creé la clase Producto.",
                model_role=request.model_role,
                model="fake-qwen",
            )

    provider = ToolCallingProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)
    message_id = uuid4()

    accepted = _post(
        client,
        test_project.id,
        message_id,
        prompt="Crea la clase Producto",
    )
    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    diagram_class = session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.name == "Producto",
        )
    ).one()
    primary_key = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == diagram_class.id,
            DiagramAttributeModel.is_primary_key.is_(True),
        )
    ).one()
    persisted = session.get(AgentMessageModel, message_id)
    assert primary_key.data_type == "UUID"
    assert persisted is not None
    assert persisted.plan["status"] == "completed"
    assert persisted.plan["operation_ledger"][0]["status"] == "applied"
    assert persisted.plan["operation_ledger"][0]["entity_refs"][0]["id"] == str(
        diagram_class.id
    )
    assert persisted.plan_version > 0
    assert len([c for c in provider.calls if c.purpose != "memory_update"]) == 2


def test_post_during_active_message_returns_conflict_without_persisting_queue(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    app.dependency_overrides[get_current_user] = lambda: owner_user
    session.add(
        AgentMessageModel(
            id=uuid4(),
            project_id=test_project.id,
            user_id=owner_user.user_id,
            prompt="Current run",
            status="running",
        )
    )
    session.commit()

    notifications_before = list(app.state.agent_job_runner.notifications)
    response = _post(client, test_project.id)

    assert response.status_code == 409
    assert app.state.agent_job_runner.notifications == notifications_before
    rows = session.exec(
        select(AgentMessageModel).where(
            AgentMessageModel.project_id == test_project.id,
            AgentMessageModel.user_id == owner_user.user_id,
        )
    ).all()
    assert len(rows) == 1


def test_controlled_provider_failure_returns_failed_and_does_not_leak_details(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    provider = FakeAiProvider(should_fail=True)
    app.dependency_overrides[get_current_user] = lambda: owner_user
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
    assert response.json()["status"] == "failed"
    assert "private provider error" not in response.text
