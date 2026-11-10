from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
    AgentComponentReservationPublisher,
)
from app.modules.assistant.domain.entities.agent_continuation import ContinuationCloseReason
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.domain.exceptions import AgentMessagePersistenceException
from app.modules.assistant.domain.repositories.agent_continuation_repository import (
    AgentContinuationRepository,
)
from app.modules.assistant.domain.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.application.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class CancelAgentMessageResult:
    message: AgentMessage
    cancellation_pending: bool


class CancelAgentMessageUseCase:
    """Registra de forma idempotente una solicitud de cancelación del autor."""

    def __init__(
        self,
        *,
        message_repository: AgentMessageRepository,
        project_access_policy: ProjectAccessPolicy,
        uow: UnitOfWork,
        reservation_publisher: AgentComponentReservationPublisher | None = None,
        continuation_repository: AgentContinuationRepository | None = None,
    ) -> None:
        self.message_repository = message_repository
        self.project_access_policy = project_access_policy
        self.uow = uow
        self.reservation_publisher = reservation_publisher
        self.continuation_repository = continuation_repository

    def execute(
        self, *, message_id: UUID, project_id: UUID, user_id: str
    ) -> CancelAgentMessageResult:
        self.project_access_policy.ensure_read_access(project_id, user_id)
        try:
            message = self.message_repository.request_cancel(
                message_id=message_id,
                project_id=project_id,
                user_id=user_id,
                now=datetime.now(timezone.utc),
            )
            if message is not None:
                if self.continuation_repository is not None:
                    self.continuation_repository.close_claimed_by_message(
                        message_id=message_id,
                        close_reason=ContinuationCloseReason.CANCELLED,
                    )
                self.uow.commit()
                if self.reservation_publisher is not None:
                    self.reservation_publisher.publish_release_sync(project_id, message_id)
                return CancelAgentMessageResult(message, cancellation_pending=True)

            current = self.message_repository.find_by_id(message_id)
            if (
                current is None
                or current.project_id != project_id
                or current.user_id != user_id
            ):
                raise ProjectNotFoundException()
            if current.status in {
                AgentMessageStatus.COMPLETED,
                AgentMessageStatus.PARTIAL,
                AgentMessageStatus.FAILED,
                AgentMessageStatus.CANCELLED,
            }:
                if current.status == AgentMessageStatus.CANCELLED:
                    if self.continuation_repository is not None:
                        self.continuation_repository.close_claimed_by_message(
                            message_id=message_id,
                            close_reason=ContinuationCloseReason.CANCELLED,
                        )
                        self.uow.commit()
                    if self.reservation_publisher is not None:
                        self.reservation_publisher.publish_release_sync(project_id, message_id)
                return CancelAgentMessageResult(current, cancellation_pending=False)
            raise ProjectNotFoundException()
        except ProjectNotFoundException:
            self.uow.rollback()
            raise
        except Exception as exc:
            self.uow.rollback()
            raise AgentMessagePersistenceException() from exc

