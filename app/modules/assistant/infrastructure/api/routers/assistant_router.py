from datetime import datetime
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.core.dependencies import CurrentUser, UoWDep
from app.core.errors.handlers import format_error
from app.modules.assistant.application.use_cases.create_agent_message import (
    CreateAgentMessageCommand,
    CreateAgentMessageUseCase,
    MAX_IMAGE_BYTES,
)
from app.modules.assistant.application.use_cases.submit_agent_message import (
    SubmitAgentMessageUseCase,
)
from app.modules.assistant.application.queries.agent_messages import AgentMessagesQueryHandler
from app.modules.assistant.application.use_cases.cancel_agent_message import (
    CancelAgentMessageUseCase,
)
from app.modules.assistant.domain.exceptions import (
    AgentMessagePersistenceException,
    ImageStorageUnavailableException,
    InvalidAgentMessageException,
)
from app.modules.assistant.infrastructure.api.schemas.agent_message_schemas import (
    AgentMessageActiveRead,
    AgentMessageCreatedRead,
    AgentMessagePageRead,
    AgentMessageRead,
)
from app.modules.assistant.infrastructure.external.cloudinary_image_provider import (
    CloudinaryImageProvider,
)
from app.modules.assistant.infrastructure.realtime.agent_acceptance_publisher import (
    WebSocketAgentAcceptancePublisher,
)
from app.modules.assistant.infrastructure.realtime.agent_component_reservation_publisher import (
    WebSocketAgentComponentReservationPublisher,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_author_name_reader import (
    SQLModelAgentAuthorNameReader,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(prefix="/projects/{project_id}/assistant/messages", tags=["Assistant"])
logger = logging.getLogger(__name__)


def _build_query_handler(uow: UoWDep) -> AgentMessagesQueryHandler:
    session = uow.session
    return AgentMessagesQueryHandler(
        message_repository=SQLModelAgentMessageRepository(session),
        access_policy=ProjectAccessPolicy(
            project_repository=SQLModelProjectRepository(session),
            project_member_repository=SQLModelProjectMemberRepository(session),
        ),
        author_name_reader=SQLModelAgentAuthorNameReader(session),
    )


@router.get("", response_model=AgentMessagePageRead)
def list_agent_messages(
    project_id: UUID,
    current_user: CurrentUser,
    uow: UoWDep,
    limit: int = Query(default=6, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    snapshot_at: datetime | None = None,
) -> AgentMessagePageRead:
    page = _build_query_handler(uow).list_messages(
        project_id=project_id,
        user_id=current_user.user_id,
        limit=limit,
        offset=offset,
        snapshot_at=snapshot_at,
    )
    return AgentMessagePageRead(
        items=[AgentMessageRead.model_validate(item) for item in page.items],
        limit=page.limit,
        offset=page.offset,
        next_offset=page.next_offset,
        has_more=page.has_more,
        snapshot_at=page.snapshot_at,
    )


@router.get("/active", response_model=AgentMessageActiveRead)
def get_active_agent_message(
    project_id: UUID,
    current_user: CurrentUser,
    uow: UoWDep,
) -> AgentMessageActiveRead:
    message = _build_query_handler(uow).get_active(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    return AgentMessageActiveRead(
        message=AgentMessageRead.model_validate(message) if message is not None else None
    )


@router.get("/{message_id}", response_model=AgentMessageRead)
def get_agent_message(
    project_id: UUID,
    message_id: UUID,
    current_user: CurrentUser,
    uow: UoWDep,
) -> AgentMessageRead:
    message = _build_query_handler(uow).get_message(
        project_id=project_id,
        user_id=current_user.user_id,
        message_id=message_id,
    )
    return AgentMessageRead.model_validate(message)


@router.post("/{message_id}/cancel", response_model=AgentMessageRead)
def cancel_agent_message(
    project_id: UUID,
    message_id: UUID,
    current_user: CurrentUser,
    uow: UoWDep,
    response: Response,
) -> AgentMessageRead | JSONResponse:
    session = uow.session
    use_case = CancelAgentMessageUseCase(
        message_repository=SQLModelAgentMessageRepository(session),
        project_access_policy=ProjectAccessPolicy(
            project_repository=SQLModelProjectRepository(session),
            project_member_repository=SQLModelProjectMemberRepository(session),
        ),
        uow=uow,
        reservation_publisher=WebSocketAgentComponentReservationPublisher(),
        continuation_repository=SQLModelAgentContinuationRepository(session),
    )
    try:
        result = use_case.execute(
            message_id=message_id,
            project_id=project_id,
            user_id=current_user.user_id,
        )
    except ProjectNotFoundException as exc:
        return JSONResponse(status_code=404, content=format_error(exc.code, exc.message))
    except AgentMessagePersistenceException as exc:
        return JSONResponse(status_code=503, content=format_error(exc.code, exc.message))

    response.status_code = (
        status.HTTP_202_ACCEPTED if result.cancellation_pending else status.HTTP_200_OK
    )
    view = _build_query_handler(uow).get_message(
        project_id=project_id,
        user_id=current_user.user_id,
        message_id=message_id,
    )
    return AgentMessageRead.model_validate(view)


def _build_create_use_case(uow: UoWDep) -> CreateAgentMessageUseCase:
    session = uow.session
    access_policy = ProjectAccessPolicy(
        project_repository=SQLModelProjectRepository(session),
        project_member_repository=SQLModelProjectMemberRepository(session),
    )
    return CreateAgentMessageUseCase(
        project_access_policy=access_policy,
        message_repository=SQLModelAgentMessageRepository(session),
        image_storage=CloudinaryImageProvider(),
        uow=uow,
    )


async def _read_form_payload(request: Request) -> tuple[UUID, str, bytes | None, str | None]:
    if "multipart/form-data" not in request.headers.get("content-type", "").lower():
        raise HTTPException(status_code=422, detail="Se requiere multipart/form-data.")

    try:
        async with request.form(max_files=1, max_fields=5) as form:
            items = form.multi_items()
            keys = [key for key, _ in items]
            if set(keys) - {"message_id", "prompt", "image"}:
                raise HTTPException(
                    status_code=422,
                    detail="El formulario contiene campos no permitidos.",
                )
            if (
                keys.count("message_id") != 1
                or keys.count("prompt") != 1
                or keys.count("image") > 1
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Los campos del formulario están duplicados o incompletos.",
                )

            raw_message_id = form.get("message_id")
            prompt = form.get("prompt")
            image = form.get("image")
            if not isinstance(raw_message_id, str) or not isinstance(prompt, str):
                raise HTTPException(
                    status_code=422,
                    detail="message_id y prompt deben ser texto.",
                )
            try:
                message_id = UUID(raw_message_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="message_id debe ser un UUID válido.",
                ) from exc

            image_data: bytes | None = None
            image_content_type: str | None = None
            if image is not None:
                if not isinstance(image, UploadFile):
                    raise HTTPException(status_code=422, detail="image debe ser un archivo.")
                image_data = await image.read(MAX_IMAGE_BYTES + 1)
                image_content_type = image.content_type
                if len(image_data) > MAX_IMAGE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="La imagen supera el límite de 10 MiB.",
                    )
            return message_id, prompt, image_data, image_content_type
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="El formulario multipart no es válido.",
        ) from exc


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AgentMessageCreatedRead)
async def create_agent_message(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    uow: UoWDep,
    response: Response,
) -> AgentMessageCreatedRead:
    """Acepta el mensaje persistido sin esperar la ejecución del agente."""
    message_id, prompt, image_data, image_content_type = await _read_form_payload(request)

    try:
        runner = getattr(request.app.state, "agent_job_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="El worker del asistente no está disponible.")
        author_profile = SQLModelAgentAuthorNameReader(uow.session).find_profiles(
            {current_user.user_id}
        ).get(current_user.user_id)
        author_name = (
            author_profile.name if author_profile and author_profile.name
            else current_user.name or current_user.user_id
        )
        author_avatar_url = author_profile.avatar_url if author_profile else None
        submitted = await SubmitAgentMessageUseCase(
            create_message=_build_create_use_case(uow),
            dispatcher=runner,
            acceptance_publisher=WebSocketAgentAcceptancePublisher(),
        ).execute(
            CreateAgentMessageCommand(
                message_id=message_id,
                project_id=project_id,
                user_id=current_user.user_id,
                prompt=prompt,
                image_data=image_data,
                image_content_type=image_content_type,
            ),
            author_name=author_name,
            author_avatar_url=author_avatar_url,
        )
        result = submitted.message
    except ProjectNotFoundException as exc:
        return JSONResponse(status_code=404, content=format_error(exc.code, exc.message))
    except InvalidAgentMessageException as exc:
        return JSONResponse(
            status_code=422,
            content=format_error(exc.code, exc.message),
        )
    except AgentMessagePersistenceException as exc:
        return JSONResponse(status_code=503, content=format_error(exc.code, exc.message))
    except ImageStorageUnavailableException as exc:
        return JSONResponse(status_code=503, content=format_error(exc.code, exc.message))

    response.status_code = (
        status.HTTP_200_OK if result.was_existing else status.HTTP_202_ACCEPTED
    )
    return AgentMessageCreatedRead(
        message_id=result.message_id,
        project_id=result.project_id,
        status=result.status,
        image_url=result.image_url,
        prompt=result.prompt,
        user_id=result.user_id,
        author_name=author_name,
        author_avatar_url=author_avatar_url,
        cancel_requested=result.cancel_requested,
        created_at=result.created_at,
        response_markdown=result.response_markdown,
    )
