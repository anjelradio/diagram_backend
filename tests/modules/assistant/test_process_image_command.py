import io
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiAction,
    AiInterpretationResult,
)
from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.enums.agent_activity_state import AgentActivityState
from app.modules.assistant.domain.exceptions import (
    AiServiceUnavailableException,
)
from app.modules.assistant.infrastructure.persistence.models.agent_activity_model import (
    AgentActivityModel,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
    SQLModelAgentActivityRepository,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_process_image_command_success(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    mock_ai_result = AiInterpretationResult(
        transcription=None,
        resume="Se identificaron 2 clases: Cliente y Factura con relación 1:N.",
        actions=[
            AiAction(
                type=AgentActionType.CREATE_CLASS,
                payload={"name": "Cliente", "position_x": 100.0, "position_y": 100.0},
            ),
            AiAction(
                type=AgentActionType.CREATE_ATTRIBUTE,
                payload={
                    "class_name": "Cliente",
                    "name": "nombre",
                    "data_type": "TEXT",
                },
            ),
            AiAction(
                type=AgentActionType.CREATE_CLASS,
                payload={"name": "Factura", "position_x": 400.0, "position_y": 100.0},
            ),
        ],
    )

    with (
        patch(
            "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_image_command",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch(
            "app.modules.assistant.infrastructure.external.cloudinary_image_provider.CloudinaryImageProvider.upload",
            new_callable=AsyncMock,
            return_value="https://res.cloudinary.com/demo/image/upload/sample.png",
        ),
    ):
        img_file = io.BytesIO(b"fake image bytes png")
        response = client.post(
            "/api/assistant/image",
            data={"project_id": str(test_project.id), "prompt": "Recrear diagrama"},
            files={"image": ("diagram.png", img_file, "image/png")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "FINISHED"
    assert data["image_url"] == "https://res.cloudinary.com/demo/image/upload/sample.png"
    assert data["actions_count"] == 3
    assert len(data["actions"]) == 3

    # Verificar persistencia en base de datos
    stmt_classes = select(DiagramClassModel).where(
        DiagramClassModel.project_id == test_project.id,
    )
    db_classes = session.exec(stmt_classes).all()
    class_names = {c.name for c in db_classes}
    assert "Cliente" in class_names
    assert "Factura" in class_names


def test_process_image_command_invalid_mime(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    pdf_file = io.BytesIO(b"%PDF-1.4 fake pdf")
    response = client.post(
        "/api/assistant/image",
        data={"project_id": str(test_project.id)},
        files={"image": ("doc.pdf", pdf_file, "application/pdf")},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "INVALID_IMAGE_FORMAT"


def test_process_image_command_unauthorized_reader(
    client: TestClient,
    test_project: ProjectModel,
    reader_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: reader_user

    img_file = io.BytesIO(b"fake image bytes")
    response = client.post(
        "/api/assistant/image",
        data={"project_id": str(test_project.id)},
        files={"image": ("diagram.png", img_file, "image/png")},
    )

    assert response.status_code == 403


def test_process_image_command_concurrency_conflict(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Crear una actividad activa preexistente
    active_activity = AgentActivity.create(project_id=test_project.id)
    repo = SQLModelAgentActivityRepository(session)
    repo.save(active_activity)
    session.commit()

    img_file = io.BytesIO(b"fake image bytes")
    response = client.post(
        "/api/assistant/image",
        data={"project_id": str(test_project.id)},
        files={"image": ("diagram.png", img_file, "image/png")},
    )

    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "ACTIVE_ACTIVITY_CONFLICT"


def test_process_image_command_ai_unavailable(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    with patch(
        "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_image_command",
        new_callable=AsyncMock,
        side_effect=AiServiceUnavailableException("Gemini quota exceeded"),
    ):
        img_file = io.BytesIO(b"fake image bytes")
        response = client.post(
            "/api/assistant/image",
            data={"project_id": str(test_project.id)},
            files={"image": ("diagram.png", img_file, "image/png")},
        )

    assert response.status_code == 503
    data = response.json()
    assert data["error"]["code"] == "AI_SERVICE_UNAVAILABLE"
