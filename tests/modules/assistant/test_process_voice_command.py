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
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.exceptions import (
    AiServiceUnavailableException,
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


def test_process_voice_command_success(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    mock_ai_result = AiInterpretationResult(
        transcription="Crear clase Persona con atributo edad entero",
        resume="Se creará la clase Persona y el atributo edad.",
        actions=[
            AiAction(
                type=AgentActionType.CREATE_CLASS,
                payload={"name": "Persona", "position_x": 200.0, "position_y": 200.0},
            ),
            AiAction(
                type=AgentActionType.CREATE_ATTRIBUTE,
                payload={
                    "class_name": "Persona",
                    "name": "edad",
                    "data_type": "INTEGER",
                },
            ),
        ],
    )

    with patch(
        "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
        new_callable=AsyncMock,
        return_value=mock_ai_result,
    ):
        audio_file = io.BytesIO(b"fake audio bytes")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "FINISHED"
    assert data["transcription"] == "Crear clase Persona con atributo edad entero"
    assert data["actions_count"] == 2
    assert len(data["actions"]) == 2

    # Verificar persistencia en base de datos
    stmt_class = select(DiagramClassModel).where(
        DiagramClassModel.project_id == test_project.id,
        DiagramClassModel.name == "Persona",
    )
    db_class = session.exec(stmt_class).first()
    assert db_class is not None

    stmt_attrs = select(DiagramAttributeModel).where(
        DiagramAttributeModel.class_id == db_class.id
    )
    attrs = session.exec(stmt_attrs).all()
    attr_names = {a.name for a in attrs}
    assert "id" in attr_names
    assert "edad" in attr_names


def test_process_voice_command_unauthorized_reader(
    client: TestClient,
    test_project: ProjectModel,
    reader_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: reader_user

    audio_file = io.BytesIO(b"fake audio bytes")
    response = client.post(
        "/api/assistant/voice",
        data={"project_id": str(test_project.id)},
        files={"audio": ("audio.wav", audio_file, "audio/wav")},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WRITE_FORBIDDEN"


def test_process_voice_command_invalid_audio_format(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    text_file = io.BytesIO(b"not an audio")
    response = client.post(
        "/api/assistant/voice",
        data={"project_id": str(test_project.id)},
        files={"audio": ("file.txt", text_file, "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AUDIO_FORMAT"


def test_process_voice_command_empty_actions(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    mock_ai_result = AiInterpretationResult(
        transcription="Hola, qué tal el clima hoy",
        resume="La petición no contiene órdenes sobre el diagrama.",
        actions=[],
    )

    with patch(
        "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
        new_callable=AsyncMock,
        return_value=mock_ai_result,
    ):
        audio_file = io.BytesIO(b"fake audio")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.ogg", audio_file, "audio/ogg")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "FINISHED"
    assert data["actions_count"] == 0
    assert data["actions"] == []


def test_process_voice_command_ai_service_unavailable(
    client: TestClient,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    with patch(
        "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
        new_callable=AsyncMock,
        side_effect=AiServiceUnavailableException("Quota exceeded"),
    ):
        audio_file = io.BytesIO(b"fake audio")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.mp3", audio_file, "audio/mp3")},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_SERVICE_UNAVAILABLE"


def test_process_voice_command_concurrent_active_conflict_returns_409(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Simular una actividad ya en progreso
    from app.modules.assistant.domain.entities.agent_activity import AgentActivity
    from app.modules.assistant.domain.enums.agent_activity_state import AgentActivityState
    from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
        SQLModelAgentActivityRepository,
    )
    import uuid

    repo = SQLModelAgentActivityRepository(session)
    active_act = AgentActivity(
        id=uuid.uuid4(),
        project_id=test_project.id,
        state=AgentActivityState.IN_PROGRESS,
    )
    repo.save(active_act)
    session.commit()

    audio_file = io.BytesIO(b"audio bytes")
    response = client.post(
        "/api/assistant/voice",
        data={"project_id": str(test_project.id)},
        files={"audio": ("audio.wav", audio_file, "audio/wav")},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_ACTIVITY_CONFLICT"


def test_process_voice_command_broadcast_sequencing(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    mock_ai_result = AiInterpretationResult(
        transcription="Crear clase Producto",
        resume="Se creo la clase Producto.",
        actions=[
            AiAction(
                type=AgentActionType.CREATE_CLASS,
                payload={"name": "Producto", "position_x": 100.0, "position_y": 150.0},
            ),
        ],
    )

    broadcast_calls = []

    async def mock_broadcast_lock(project_id, user_id, activity_id):
        broadcast_calls.append(("lock", activity_id))

    async def mock_broadcast_finished(project_id, user_id, activity_id, state):
        broadcast_calls.append(("finished", activity_id, state))

    async def mock_broadcast(project_id, payload):
        broadcast_calls.append(("mutation", payload.get("operation_type")))

    with (
        patch(
            "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch(
            "app.modules.diagram.infrastructure.realtime.connection_manager.ConnectionManager.broadcast_agent_lock",
            side_effect=mock_broadcast_lock,
        ),
        patch(
            "app.modules.diagram.infrastructure.realtime.connection_manager.ConnectionManager.broadcast_agent_finished",
            side_effect=mock_broadcast_finished,
        ),
        patch(
            "app.modules.diagram.infrastructure.realtime.connection_manager.ConnectionManager.broadcast",
            side_effect=mock_broadcast,
        ),
    ):
        audio_file = io.BytesIO(b"fake audio bytes")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 201
    assert len(broadcast_calls) >= 3
    # Primero lock
    assert broadcast_calls[0][0] == "lock"
    # Luego mutaciones
    assert any(c[0] == "mutation" for c in broadcast_calls)
    # Finalmente finished con FINISHED
    assert broadcast_calls[-1][0] == "finished"
    assert broadcast_calls[-1][2] == "FINISHED"


def test_process_voice_command_rollback_on_failed_action(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Intentar eliminar una clase que no existe en el diagrama
    mock_ai_result = AiInterpretationResult(
        transcription="Eliminar clase Inexistente",
        resume="Eliminando clase...",
        actions=[
            AiAction(
                type=AgentActionType.DELETE_CLASS,
                payload={"name": "ClaseFantasma"},
            ),
        ],
    )

    finished_events = []

    async def mock_broadcast_finished(project_id, user_id, activity_id, state):
        finished_events.append(state)

    with (
        patch(
            "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch(
            "app.modules.diagram.infrastructure.realtime.connection_manager.ConnectionManager.broadcast_agent_finished",
            side_effect=mock_broadcast_finished,
        ),
    ):
        audio_file = io.BytesIO(b"fake audio")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 422
    assert finished_events == ["FAILED"]


def test_process_voice_command_create_attribute_single_canonical_mutation(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: owner_user

    # Crear una clase previa en la base de datos
    class_model = DiagramClassModel(
        project_id=test_project.id,
        name="Articulo",
        position_x=100.0,
        position_y=100.0,
    )
    session.add(class_model)
    session.flush()

    pk_attr = DiagramAttributeModel(
        class_id=class_model.id,
        name="id",
        data_type="UUID",
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    session.add(pk_attr)
    session.commit()

    mock_ai_result = AiInterpretationResult(
        transcription="Añadir atributo precio decimal a Articulo",
        resume="Se añadirá el atributo precio.",
        actions=[
            AiAction(
                type=AgentActionType.CREATE_ATTRIBUTE,
                payload={
                    "class_name": "Articulo",
                    "name": "precio",
                    "data_type": "DECIMAL",
                    "is_nullable": True,
                },
            ),
        ],
    )

    broadcast_mutations = []

    async def mock_broadcast(project_id, payload):
        if payload.get("type") == "diagram_mutation":
            broadcast_mutations.append(payload.get("operation_type"))

    with (
        patch(
            "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch(
            "app.modules.diagram.infrastructure.realtime.connection_manager.ConnectionManager.broadcast",
            side_effect=mock_broadcast,
        ),
    ):
        audio_file = io.BytesIO(b"fake audio bytes")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 201
    # Debe publicar una sola mutación canónica para el atributo (CREATE_ATTRIBUTE), sin un UPDATE_ATTRIBUTE posterior
    assert broadcast_mutations == ["CREATE_ATTRIBUTE"]


def test_process_voice_command_revalidates_permissions_before_batch(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
    editor_user: AuthUser,
) -> None:
    # Simular que el usuario era editor al inicio pero pierde permisos durante la interpretación
    app.dependency_overrides[get_current_user] = lambda: editor_user

    mock_ai_result = AiInterpretationResult(
        transcription="Crear clase Test",
        resume="Creando clase...",
        actions=[
            AiAction(
                type=AgentActionType.CREATE_CLASS,
                payload={"name": "TestClass", "position_x": 100.0, "position_y": 100.0},
            ),
        ],
    )

    call_count = 0
    from app.modules.diagram.application.services.diagram_access_policy import (
        DiagramAccessPolicy,
    )
    from app.modules.diagram.domain.exceptions import DiagramWriteForbiddenException

    original_ensure_write = DiagramAccessPolicy.ensure_write_access

    def mock_ensure_write(self, project_id, user_id, ignore_agent_lock=False):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            # En la segunda llamada (revalidación antes del lote), simula degradación/revocación
            raise DiagramWriteForbiddenException()
        return original_ensure_write(self, project_id, user_id, ignore_agent_lock=ignore_agent_lock)

    with (
        patch(
            "app.modules.assistant.infrastructure.external.gemini_ai_provider.GeminiAiProvider.interpret_voice_command",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch.object(
            DiagramAccessPolicy,
            "ensure_write_access",
            mock_ensure_write,
        ),
    ):
        audio_file = io.BytesIO(b"fake audio")
        response = client.post(
            "/api/assistant/voice",
            data={"project_id": str(test_project.id)},
            files={"audio": ("audio.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WRITE_FORBIDDEN"

