import logging
import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.providers.image_storage_provider import (
    ImageStorageProvider,
    StoredImage,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.exceptions import (
    AgentAlreadyActiveException,
    AgentMessageAlreadyExistsException,
    AgentMessagePersistenceException,
    ImageStorageUnavailableException,
    InvalidAgentMessageException,
)
from app.modules.assistant.domain.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.application.ports import UnitOfWork

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


@dataclass(frozen=True, slots=True)
class CreateAgentMessageCommand:
    message_id: UUID
    project_id: UUID
    user_id: str
    prompt: str
    image_data: bytes | None = None
    image_content_type: str | None = None


@dataclass(frozen=True, slots=True)
class CreatedAgentMessage:
    message_id: UUID
    project_id: UUID
    status: str
    image_url: str | None
    prompt: str
    user_id: str
    created_at: datetime
    response_markdown: str | None = None
    cancel_requested: bool = False
    was_existing: bool = False


class CreateAgentMessageUseCase:
    """Valida acceso, sube la imagen opcional y persiste el mensaje."""

    def __init__(
        self,
        *,
        project_access_policy: ProjectAccessPolicy,
        message_repository: AgentMessageRepository,
        image_storage: ImageStorageProvider,
        uow: UnitOfWork,
    ) -> None:
        self.project_access_policy = project_access_policy
        self.message_repository = message_repository
        self.image_storage = image_storage
        self.uow = uow

    async def execute(self, command: CreateAgentMessageCommand) -> CreatedAgentMessage:
        prompt = command.prompt.strip() if isinstance(command.prompt, str) else ""
        if not prompt or len(prompt) > 10_000:
            raise InvalidAgentMessageException(
                "El prompt debe contener entre 1 y 10000 caracteres."
            )
        if command.image_data is not None:
            self._validate_image(command.image_data, command.image_content_type)

        self.project_access_policy.ensure_read_access(command.project_id, command.user_id)
        fingerprint = _request_fingerprint(
            prompt,
            command.image_content_type,
            command.image_data,
        )
        existing = self.message_repository.find_by_id(command.message_id)
        if existing is not None:
            if _matches_retry(existing, command, fingerprint):
                return _to_created(existing, was_existing=True)
            raise AgentMessageAlreadyExistsException()

        stored_image: StoredImage | None = None
        commit_attempted = False
        try:
            if command.image_data is not None:
                # Libera la transacción de lectura previa antes de esperar la red.
                self.uow.rollback()
                stored_image = await self.image_storage.upload(
                    command.image_data,
                    public_id=f"agent/messages/{uuid4().hex}",
                )

            # El acceso puede cambiar mientras termina la carga externa.
            self.project_access_policy.ensure_read_access(command.project_id, command.user_id)
            message = AgentMessage.register(
                id=command.message_id,
                project_id=command.project_id,
                user_id=command.user_id,
                prompt=prompt,
                image_url=stored_image.url if stored_image else None,
                request_fingerprint=fingerprint,
            )
            self.message_repository.save_new(message)
            commit_attempted = True
            self.uow.commit()
        except AgentMessageAlreadyExistsException:
            self.uow.rollback()
            existing = self.message_repository.find_by_id(command.message_id)
            if stored_image is not None:
                await self._compensate(stored_image)
            if existing is not None and _matches_retry(existing, command, fingerprint):
                return _to_created(existing, was_existing=True)
            raise
        except AgentAlreadyActiveException:
            if stored_image is not None:
                await self._compensate(stored_image)
            raise
        except ProjectNotFoundException:
            if stored_image is not None:
                await self._compensate(stored_image)
            raise
        except ImageStorageUnavailableException:
            raise
        except Exception as exc:
            if stored_image is not None:
                if not commit_attempted:
                    await self._compensate(stored_image)
                else:
                    referenced = self.message_repository.image_url_is_referenced(
                        command.message_id, stored_image.url
                    )
                    if referenced is False:
                        await self._compensate(stored_image)
                    elif referenced is None:
                        logger.exception(
                            "No se pudo comprobar la referencia de una imagen tras un commit incierto"
                        )
            if isinstance(exc, InvalidAgentMessageException):
                raise
            if isinstance(exc, ImageStorageUnavailableException):
                raise
            raise AgentMessagePersistenceException() from exc

        return _to_created(message)

    @staticmethod
    def _validate_image(image_data: bytes, content_type: str | None) -> None:
        if not image_data:
            raise InvalidAgentMessageException("La imagen no puede estar vacía.")
        if len(image_data) > MAX_IMAGE_BYTES:
            raise InvalidAgentMessageException("La imagen supera el límite de 10 MiB.")
        signatures = {
            "image/png": image_data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": image_data.startswith(b"\xff\xd8\xff"),
            "image/webp": (
                len(image_data) >= 12
                and image_data.startswith(b"RIFF")
                and image_data[8:12] == b"WEBP"
            ),
        }
        if content_type not in ALLOWED_IMAGE_TYPES or not signatures.get(content_type, False):
            raise InvalidAgentMessageException("La imagen debe ser PNG, JPEG o WebP válido.")

    async def _compensate(self, image: StoredImage) -> None:
        try:
            await self.image_storage.delete(image.public_id)
        except Exception:
            logger.exception(
                "No se pudo compensar el activo Cloudinary creado por el intento %s",
                image.public_id,
            )


def _request_fingerprint(
    prompt: str, content_type: str | None, image_data: bytes | None
) -> str:
    digest = hashlib.sha256()
    for part in (prompt.encode("utf-8"), (content_type or "").encode("utf-8"), image_data or b""):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _matches_retry(message: AgentMessage, command: CreateAgentMessageCommand, fingerprint: str) -> bool:
    return (
        message.project_id == command.project_id
        and message.user_id == command.user_id
        and message.request_fingerprint == fingerprint
    )


def _to_created(
    message: AgentMessage, *, was_existing: bool = False
) -> CreatedAgentMessage:
    return CreatedAgentMessage(
        message_id=message.id,
        project_id=message.project_id,
        status=message.status.value,
        image_url=message.image_url,
        prompt=message.prompt,
        user_id=message.user_id,
        created_at=message.created_at,
        response_markdown=message.response_markdown,
        cancel_requested=message.cancel_requested_at is not None,
        was_existing=was_existing,
    )
