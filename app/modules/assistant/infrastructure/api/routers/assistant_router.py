from uuid import UUID
from fastapi import APIRouter, File, Form, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.dependencies import CurrentUser, UoWDep
from app.core.errors.handlers import format_error
from app.modules.assistant.application.services.action_executor import (
    ActionExecutor,
    AtomicBatchUnitOfWork,
)
from app.modules.assistant.application.services.action_planner import (
    ActionPlanner,
)
from app.modules.assistant.application.use_cases.process_voice_command import (
    ProcessVoiceCommand,
    ProcessVoiceCommandUseCase,
)
from app.modules.assistant.domain.exceptions import (
    AgentActionValidationException,
    AgentAlreadyActiveException,
    AgentInterpretationFailedException,
    AiServiceUnavailableException,
    InvalidAudioFormatException,
)
from app.modules.assistant.infrastructure.api.schemas.assistant_schemas import (
    ActionResultRead,
    AgentActivityListItemRead,
    VoiceCommandResultRead,
)
from app.modules.assistant.infrastructure.external.gemini_ai_provider import (
    GeminiAiProvider,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_activity_repository import (
    SQLModelAgentActivityRepository,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.exceptions import DiagramWriteForbiddenException
from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_diagram_snapshot_reader import (
    SQLModelDiagramSnapshotReader,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    connection_manager,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(prefix="/assistant", tags=["Asistente"])


@router.post(
    "/voice",
    response_model=VoiceCommandResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Procesar comando de voz para editar diagrama",
)
async def process_voice_command(
    project_id: UUID = Form(..., description="ID del proyecto del diagrama"),
    audio: UploadFile = File(..., description="Archivo de audio con la orden de voz"),
    current_user: CurrentUser = None,
    uow: UoWDep = None,
) -> VoiceCommandResultRead | Response:
    audio_data = await audio.read()
    audio_mime = audio.content_type or "audio/wav"

    project_repo = SQLModelProjectRepository(uow.session)
    member_repo = SQLModelProjectMemberRepository(uow.session)
    access_policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )

    batch_uow = AtomicBatchUnitOfWork(real_uow=uow)
    class_repo = SQLModelDiagramClassRepository(uow.session)
    attr_repo = SQLModelDiagramAttributeRepository(uow.session)
    rel_repo = SQLModelDiagramRelationRepository(uow.session)
    activity_repo = SQLModelAgentActivityRepository(uow.session)
    snapshot_reader = SQLModelDiagramSnapshotReader(uow.session)

    planner = ActionPlanner()
    executor = ActionExecutor(
        access_policy=access_policy,
        diagram_class_repository=class_repo,
        diagram_attribute_repository=attr_repo,
        diagram_relation_repository=rel_repo,
        batch_uow=batch_uow,
    )
    ai_provider = GeminiAiProvider()

    use_case = ProcessVoiceCommandUseCase(
        access_policy=access_policy,
        ai_provider=ai_provider,
        agent_activity_repository=activity_repo,
        diagram_snapshot_reader=snapshot_reader,
        action_planner=planner,
        action_executor=executor,
        batch_uow=batch_uow,
        real_uow=uow,
        connection_manager=connection_manager,
    )

    try:
        dto = await use_case.execute(
            ProcessVoiceCommand(
                project_id=project_id,
                user_id=current_user.user_id,
                audio_data=audio_data,
                audio_mime_type=audio_mime,
            )
        )

        return VoiceCommandResultRead(
            activity_id=dto.activity_id,
            state=dto.state,
            transcription=dto.transcription,
            resume=dto.resume,
            actions_count=dto.actions_count,
            actions=[
                ActionResultRead(
                    type=a["type"],
                    status=a["status"],
                    summary=a["summary"],
                )
                for a in dto.actions
            ],
        )

    except InvalidAudioFormatException as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=format_error(exc.code, exc.message),
        )
    except DiagramWriteForbiddenException as exc:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=format_error(exc.code, exc.message),
        )
    except AgentAlreadyActiveException as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=format_error(exc.code, exc.message),
        )
    except ProjectNotFoundException as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=format_error(exc.code, exc.message),
        )
    except AgentInterpretationFailedException as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=format_error(exc.code, exc.message),
        )
    except AgentActionValidationException as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=format_error(exc.code, exc.message),
        )
    except AiServiceUnavailableException as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=format_error(exc.code, exc.message),
        )


@router.get(
    "/projects/{project_id}/activities",
    response_model=list[AgentActivityListItemRead],
    status_code=status.HTTP_200_OK,
    summary="Listar historial de actividades del asistente para un proyecto",
)
def list_project_activities(
    project_id: UUID,
    current_user: CurrentUser = None,
    uow: UoWDep = None,
) -> list[AgentActivityListItemRead] | Response:
    project_repo = SQLModelProjectRepository(uow.session)
    member_repo = SQLModelProjectMemberRepository(uow.session)
    access_policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )

    try:
        access_policy.ensure_read_access(
            project_id=project_id,
            user_id=current_user.user_id,
        )
    except ProjectNotFoundException as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=format_error(exc.code, exc.message),
        )

    activity_repo = SQLModelAgentActivityRepository(uow.session)
    activities = activity_repo.find_all_by_project_id(project_id)

    return [
        AgentActivityListItemRead(
            id=a.id,
            project_id=a.project_id,
            transcription=a.transcription,
            resume=a.resume,
            image_url=a.image_url,
            state=a.state.value if hasattr(a.state, "value") else str(a.state),
            created_date=a.created_date,
        )
        for a in activities
    ]
