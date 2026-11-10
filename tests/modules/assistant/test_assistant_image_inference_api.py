from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.ports.providers.image_storage_provider import StoredImage
from app.modules.assistant.infrastructure.api.routers import assistant_router
from app.modules.assistant.infrastructure.services import agent_runtime_factory
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import DiagramClassModel
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import DiagramAttributeModel
from tests.modules.diagram.conftest import create_test_attribute, create_test_class
from tests.modules.assistant.agent_test_helpers import process_and_fetch_message


class FakeCloudinaryProvider:
    async def upload(self, image_data: bytes, *, public_id: str):
        assert image_data.startswith(b"\x89PNG\r\n\x1a\n")
        return StoredImage(
            url="https://res.cloudinary.com/test/image/upload/persisted.png",
            public_id=public_id,
        )

    async def delete(self, _public_id: str) -> None:
        pass


class FakeAiProvider:
    def __init__(self, *, fail_vision=False):
        self.calls = []
        self.fail_vision = fail_vision

    async def complete(self, request):
        self.calls.append(request)
        if request.model_role is ModelRole.VISION and self.fail_vision:
            raise RuntimeError("private vision failure")
        if request.model_role is ModelRole.PLANNING:
            answer = (
                '{"mode":"analyze","needs_image":true,'
                '"visual_request":"Describir el diagrama",'
                '"scope":{"classes":"all","attributes":"all","relations":"all"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            answer = (
                '{"supported":true,"diagram_kind":"UML_CLASS",'
                '"classes":[{"name":"Producto","attributes":[]}],'
                '"relations":[],"uncertainties":[]}'
            )
        else:
            answer = "## Análisis\nVeo un diagrama de clases."
        return AiResult(
            text=answer,
            model_role=request.model_role,
            model=f"fake-{request.model_role.value}",
        )


def _post(client, project_id, message_id=None):
    return client.post(
        f"/api/projects/{project_id}/assistant/messages",
        files={
            "message_id": (None, str(message_id or uuid4())),
            "prompt": (None, "Analiza el diagrama adjunto"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )


def _finish(client, session, project_id, owner_user, accepted_response):
    return process_and_fetch_message(
        client=client,
        session=session,
        project_id=project_id,
        user_id=owner_user.user_id,
        accepted_response=accepted_response,
    )


def test_image_flow_persists_cloudinary_url_then_runs_vision_before_main(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    provider = FakeAiProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = _finish(client, session, test_project.id, owner_user, accepted)

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.model_role for request in provider.calls if request.purpose != "memory_update"] == [
        ModelRole.PLANNING,
        ModelRole.VISION,
        ModelRole.MAIN,
    ]
    assert all(
        not any(getattr(part, "type", None) == "image_url" for message in request.messages
                for part in (message.content if isinstance(message.content, tuple) else ()))
        for request in provider.calls[:1]
    )
    vision_content = provider.calls[1].messages[1].content
    assert vision_content[1].image_url == response.json()["image_url"]
    main_payload = "\n".join(
        message.content for message in provider.calls[2].messages if isinstance(message.content, str)
    )
    assert '"name":"Producto"' in main_payload
    record = session.get(AgentMessageModel, UUID(response.json()["message_id"]))
    assert record is not None
    assert record.image_url == response.json()["image_url"]


def test_vision_failure_marks_message_failed_without_calling_main(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    provider = FakeAiProvider(fail_vision=True)
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = _finish(client, session, test_project.id, owner_user, accepted)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert len(provider.calls) == 2
    assert [request.model_role for request in provider.calls] == [
        ModelRole.PLANNING,
        ModelRole.VISION,
    ]
    assert "private vision failure" not in response.text


def test_attached_image_is_not_sent_to_vision_when_text_intent_does_not_need_it(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    class TextOnlyProvider(FakeAiProvider):
        async def complete(self, request):
            self.calls.append(request)
            if request.model_role is ModelRole.PLANNING:
                text = (
                    '{"mode":"analyze","needs_image":false,"visual_request":"",'
                    '"scope":{},"independent_tasks":["Responde una pregunta textual"],'
                    '"clarification":null}'
                )
            else:
                text = "La respuesta no requiere consultar la imagen."
            return AiResult(text=text, model_role=request.model_role, model="fake")

    provider = TextOnlyProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = _post(client, test_project.id)
    response = _finish(client, session, test_project.id, owner_user, accepted)

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.model_role for request in provider.calls if request.purpose != "memory_update"] == [
        ModelRole.PLANNING,
        ModelRole.MAIN,
    ]
    assert all(
        not any(getattr(part, "type", None) == "image_url" for message in request.messages
                for part in (message.content if isinstance(message.content, tuple) else ()))
        for request in provider.calls
    )


@pytest.mark.parametrize(
    ("vision_case", "expected_status", "expected_roles"),
    [
        ("unsupported", "completed", [ModelRole.PLANNING, ModelRole.VISION]),
        ("uncertain", "completed", [ModelRole.PLANNING, ModelRole.VISION]),
        ("invalid-json", "failed", [ModelRole.PLANNING, ModelRole.VISION]),
    ],
)
def test_visual_guard_aborts_all_tasks_before_tools_for_bad_or_uncertain_evidence(
    vision_case,
    expected_status,
    expected_roles,
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    from sqlmodel import select
    from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import DiagramClassModel

    class GuardProvider(FakeAiProvider):
        async def complete(self, request):
            self.calls.append(request)
            if request.model_role is ModelRole.PLANNING:
                answer = (
                    '{"mode":"mutate","needs_image":true,"visual_request":"Importa todo",'
                    '"scope":{"classes":"all","attributes":"all","relations":"all"},'
                    '"independent_tasks":["Crea la clase Auditoria"],"clarification":null}'
                )
            elif vision_case == "unsupported":
                answer = (
                    '{"supported":false,"diagram_kind":"OTHER","classes":[],"relations":[],"uncertainties":[]}'
                )
            elif vision_case == "uncertain":
                answer = (
                    '{"supported":true,"diagram_kind":"ERD","classes":['
                    '{"name":"A","attributes":[]},{"name":"B","attributes":[]}],'
                    '"relations":[{"source":"A","target":"B","relation_type":"ASSOCIATION"}],'
                    '"uncertainties":[]}'
                )
            else:
                answer = "{not valid json"
            return AiResult(text=answer, model_role=request.model_role, model="fake")

    provider = GuardProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Crea Auditoria y recrea el diagrama adjunto"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = _finish(client, session, test_project.id, owner_user, accepted)
    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert [request.model_role for request in provider.calls if request.purpose != "memory_update"] == expected_roles
    assert session.exec(
        select(DiagramClassModel).where(DiagramClassModel.project_id == test_project.id)
    ).all() == []


def test_visual_clarification_continues_once_with_original_cloudinary_image(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    class ClarificationProvider:
        def __init__(self):
            self.calls = []
            self.planning_calls = 0

        async def complete(self, request):
            self.calls.append(request)
            if request.model_role is ModelRole.PLANNING:
                self.planning_calls += 1
                if self.planning_calls == 1:
                    answer = (
                        '{"mode":"clarify","needs_image":true,"visual_request":"Producto",'
                        '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
                        '"independent_tasks":[],"clarification":"¿Quieres describir Producto?",'
                        '"requested_mode":"analyze"}'
                    )
                else:
                    answer = (
                        '{"mode":"analyze","needs_image":true,"visual_request":"Describir Producto",'
                        '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
                        '"independent_tasks":[],"clarification":null}'
                    )
            elif request.model_role is ModelRole.VISION:
                answer = (
                    '{"supported":true,"diagram_kind":"ERD",'
                    '"classes":[{"name":"Producto","attributes":[]}],'
                    '"relations":[],"uncertainties":[]}'
                )
            else:
                answer = "## Producto\nLa imagen muestra una clase Producto."
            return AiResult(text=answer, model_role=request.model_role, model="fake")

    provider = ClarificationProvider()
    uploads = []

    class CountingCloudinaryProvider(FakeCloudinaryProvider):
        async def upload(self, image_data: bytes, *, public_id: str):
            uploads.append(public_id)
            return await super().upload(image_data, public_id=public_id)

    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", CountingCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    original_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Analiza Producto en el diagrama adjunto"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )
    original_response = _finish(
        client, session, test_project.id, owner_user, original_accepted
    )
    assert original_response.status_code == 200
    original_message_id = UUID(original_response.json()["message_id"])
    original_image_url = original_response.json()["image_url"]
    record = session.get(AgentMessageModel, original_message_id)
    assert record.plan["kind"] == "visual_clarification"

    continuation_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Sí, describe la clase Producto"),
        },
    )

    continuation_response = _finish(
        client, session, test_project.id, owner_user, continuation_accepted
    )
    assert continuation_response.status_code == 200
    assert continuation_response.json()["status"] == "completed"
    assert len(uploads) == 1
    continuation_intent_request = [
        call for call in provider.calls if call.model_role is ModelRole.PLANNING
    ][1]
    assert original_image_url not in "\n".join(
        message.content
        for message in continuation_intent_request.messages
        if isinstance(message.content, str)
    )
    vision_requests = [call for call in provider.calls if call.model_role is ModelRole.VISION]
    assert len(vision_requests) == 1
    assert vision_requests[0].messages[1].content[1].image_url == original_image_url
    session.expire_all()
    claimed_record = session.get(AgentMessageModel, original_message_id)
    assert claimed_record.plan["claimed_by"] == continuation_response.json()["message_id"]


def test_visual_ambiguity_continuation_sends_answer_to_vision_without_reupload(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    class Provider:
        def __init__(self):
            self.vision_calls = []
            self.main_calls = 0

        async def complete(self, request):
            if request.model_role is ModelRole.PLANNING:
                text = (
                    '{"mode":"mutate","needs_image":true,"visual_request":"Producto",'
                    '"scope":{"classes":["Producto"],"attributes":"none","relations":"none"},'
                    '"independent_tasks":[],"clarification":null}'
                )
            elif request.model_role is ModelRole.VISION:
                self.vision_calls.append(request)
                classes = (
                    '[{"name":"Producto","attributes":[]},{"name":"Producto","attributes":[]}]'
                    if len(self.vision_calls) == 1
                    else '[{"name":"Producto","attributes":[]}]'
                )
                text = (
                    '{"supported":true,"diagram_kind":"UML_CLASS","classes":'
                    + classes
                    + ',"relations":[],"uncertainties":[]}'
                )
            else:
                self.main_calls += 1
                if self.main_calls == 1:
                    call = AiToolCall(
                        id="create-product",
                        name="apply_diagram_changes",
                        arguments={"actions": [{"operation_id": "create-product", "kind": "CREATE_CLASS", "name": "Producto"}]},
                    )
                    return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
                text = "Creé Producto."
            return AiResult(text=text, model_role=request.model_role, model="fake")

    provider = Provider()
    uploads = []

    class CountingCloudinaryProvider(FakeCloudinaryProvider):
        async def upload(self, image_data: bytes, *, public_id: str):
            uploads.append(public_id)
            return await super().upload(image_data, public_id=public_id)

    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", CountingCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)
    original_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Crea Producto de la imagen"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )
    original = _finish(client, session, test_project.id, owner_user, original_accepted)
    assert "varias clases" in original.json()["response_markdown"].casefold()
    assert provider.main_calls == 0

    continuation_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={"message_id": (None, str(uuid4())), "prompt": (None, "La de arriba")},
    )
    continuation = _finish(
        client, session, test_project.id, owner_user, continuation_accepted
    )
    assert continuation.json()["status"] == "completed", continuation.json()
    assert len(uploads) == 1
    assert "La de arriba" in provider.vision_calls[1].messages[1].content[0].text
    assert len(
        session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == test_project.id,
                DiagramClassModel.name == "Producto",
            )
        ).all()
    ) == 1


def test_multiple_visual_clarifications_require_a_message_reference(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    class Provider:
        def __init__(self):
            self.planning_calls = 0

        async def complete(self, request):
            if request.model_role is ModelRole.PLANNING:
                self.planning_calls += 1
                if self.planning_calls <= 2:
                    text = (
                        '{"mode":"clarify","needs_image":true,"visual_request":"Producto",'
                        '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
                        '"independent_tasks":[],"clarification":"¿Qué quieres saber?",'
                        '"requested_mode":"analyze"}'
                    )
                else:
                    text = (
                        '{"mode":"analyze","needs_image":true,"visual_request":"Producto",'
                        '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
                        '"independent_tasks":[],"clarification":null}'
                    )
            elif request.model_role is ModelRole.VISION:
                text = (
                    '{"supported":true,"diagram_kind":"ERD",'
                    '"classes":[{"name":"Producto","attributes":[]}],'
                    '"relations":[],"uncertainties":[]}'
                )
            else:
                text = "La imagen contiene Producto."
            return AiResult(text=text, model_role=request.model_role, model="fake")

    provider = Provider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)
    originals = []
    for prompt in ("Analiza la imagen A", "Analiza la imagen B"):
        accepted = client.post(
            f"/api/projects/{test_project.id}/assistant/messages",
            files={
                "message_id": (None, str(uuid4())),
                "prompt": (None, prompt),
                "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
            },
        )
        response = _finish(client, session, test_project.id, owner_user, accepted)
        assert response.status_code == 200
        originals.append(UUID(response.json()["message_id"]))

    ambiguous_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={"message_id": (None, str(uuid4())), "prompt": (None, "Continúa")},
    )
    ambiguous = _finish(client, session, test_project.id, owner_user, ambiguous_accepted)
    assert "varias aclaraciones" in ambiguous.json()["response_markdown"].casefold()
    assert provider.planning_calls == 2

    continuation_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, f"{originals[0]}: describe Producto"),
        },
    )
    continuation = _finish(
        client, session, test_project.id, owner_user, continuation_accepted
    )
    assert continuation.json()["status"] == "completed"
    session.expire_all()
    assert session.get(AgentMessageModel, originals[0]).plan["claimed_by"] == continuation.json()["message_id"]
    assert session.get(AgentMessageModel, originals[1]).plan["claimed_by"] is None


def test_ambiguous_project_class_is_clarified_and_only_selected_class_is_changed(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    first = create_test_class(session, test_project.id, name="Producto")
    second = create_test_class(session, test_project.id, name="Producto")
    create_test_attribute(session, first.id)
    create_test_attribute(session, second.id)
    session.commit()

    class Provider:
        def __init__(self):
            self.main_calls = 0

        async def complete(self, request):
            if request.model_role is ModelRole.PLANNING:
                text = (
                    '{"mode":"mutate","needs_image":true,"visual_request":"Importa Producto",'
                    '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
                    '"independent_tasks":[],"clarification":null}'
                )
            elif request.model_role is ModelRole.VISION:
                text = (
                    '{"supported":true,"diagram_kind":"ERD","classes":'
                    '[{"name":"Producto","attributes":[{"name":"nombre",'
                    '"data_type":"TEXT","key_kind":"ordinary"}]}],'
                    '"relations":[],"uncertainties":[]}'
                )
            else:
                self.main_calls += 1
                if self.main_calls in (1, 2):
                    call = AiToolCall(
                        id=f"class-{self.main_calls}",
                        name="apply_diagram_changes",
                        arguments={"actions": [{"operation_id": f"class-{self.main_calls}", "kind": "CREATE_CLASS", "name": "Producto"}]},
                    )
                    return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
                if self.main_calls == 3:
                    call = AiToolCall(
                        id="attribute",
                        name="apply_diagram_changes",
                        arguments={"actions": [{"operation_id": "attribute", "kind": "CREATE_ATTRIBUTE", "class_id": str(second.id), "name": "nombre", "data_type": "TEXT"}]},
                    )
                    return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
                text = "Añadí nombre a la clase seleccionada."
            return AiResult(text=text, model_role=request.model_role, model="fake")

    provider = Provider()
    uploads = []

    class CountingCloudinaryProvider(FakeCloudinaryProvider):
        async def upload(self, image_data: bytes, *, public_id: str):
            uploads.append(public_id)
            return await super().upload(image_data, public_id=public_id)

    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", CountingCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)
    initial_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Crea Producto de la imagen"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )
    initial = _finish(client, session, test_project.id, owner_user, initial_accepted)
    assert initial.json()["status"] == "completed"
    initial_id = UUID(initial.json()["message_id"])
    marker = session.get(AgentMessageModel, initial_id).plan
    assert set(marker["class_ambiguity"]["candidate_ids"]) == {str(first.id), str(second.id)}
    assert marker["prior_execution_plan"]["status"] == "failed"

    unclear_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={"message_id": (None, str(uuid4())), "prompt": (None, "La segunda")},
    )
    unclear = _finish(client, session, test_project.id, owner_user, unclear_accepted)
    assert "indica exactamente uno" in unclear.json()["response_markdown"].casefold()
    session.expire_all()
    assert session.get(AgentMessageModel, initial_id).plan["claimed_by"] is None

    continuation_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={"message_id": (None, str(uuid4())), "prompt": (None, str(second.id))},
    )
    continuation = _finish(
        client, session, test_project.id, owner_user, continuation_accepted
    )
    assert continuation.json()["status"] == "completed", continuation.json()
    assert len(uploads) == 1
    attributes = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.name == "nombre")
    ).all()
    assert [attribute.class_id for attribute in attributes] == [second.id]


def test_visual_deletion_requires_separate_confirmation_before_tool_execution(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    target = create_test_class(session, test_project.id, name="Producto")
    session.commit()

    class DeleteProvider:
        def __init__(self):
            self.calls = []
            self.main_calls = 0

        async def complete(self, request):
            self.calls.append(request)
            if request.model_role is ModelRole.PLANNING:
                text = (
                    '{"mode":"mutate","needs_image":true,"visual_request":"Eliminar Producto",'
                    '"scope":{"classes":["Producto"],"attributes":"none","relations":"none"},'
                    '"independent_tasks":[],"clarification":null}'
                )
            elif request.model_role is ModelRole.VISION:
                text = (
                    '{"supported":true,"diagram_kind":"ERD",'
                    '"classes":[{"name":"Producto","attributes":[]}],'
                    '"relations":[],"uncertainties":[]}'
                )
            else:
                self.main_calls += 1
                if self.main_calls == 1:
                    call = AiToolCall(
                        id="delete-product",
                        name="apply_diagram_changes",
                        arguments={
                            "actions": [
                                {
                                    "operation_id": "delete-product",
                                    "kind": "DELETE_CLASS",
                                    "class_id": str(target.id),
                                }
                            ]
                        },
                    )
                    return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
                text = "Eliminé Producto tras la confirmación."
            return AiResult(text=text, model_role=request.model_role, model="fake")

    provider = DeleteProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    initial_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Elimina la clase Producto de la imagen"),
            "image": ("diagram.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )
    initial = _finish(client, session, test_project.id, owner_user, initial_accepted)
    assert initial.status_code == 200
    assert "confirmo" in initial.json()["response_markdown"]
    assert provider.calls == []
    assert session.get(DiagramClassModel, target.id) is not None

    continuation_accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "confirmo"),
        },
    )

    continuation = _finish(
        client, session, test_project.id, owner_user, continuation_accepted
    )
    assert continuation.status_code == 200
    assert continuation.json()["status"] == "completed", continuation.json()
    assert session.get(DiagramClassModel, target.id) is None
    assert [call.model_role for call in provider.calls if call.purpose != "memory_update"] == [
        ModelRole.PLANNING,
        ModelRole.VISION,
        ModelRole.MAIN,
        ModelRole.MAIN,
    ]
