from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)


class AgentMessageMapper:
    """Convierte mensajes entre dominio y SQLModel."""

    @staticmethod
    def to_model(entity: AgentMessage) -> AgentMessageModel:
        return AgentMessageModel(
            id=entity.id,
            project_id=entity.project_id,
            user_id=entity.user_id,
            root_message_id=entity.root_message_id,
            prompt=entity.prompt,
            image_url=entity.image_url,
            response_markdown=entity.response_markdown,
            status=entity.status.value,
            plan=entity.plan,
            plan_version=entity.plan_version,
            request_fingerprint=entity.request_fingerprint,
            cancel_requested_at=entity.cancel_requested_at,
            lease_owner=entity.lease_owner,
            lease_expires_at=entity.lease_expires_at,
            lease_heartbeat_at=entity.lease_heartbeat_at,
            created_date=entity.created_at,
        )

    @staticmethod
    def to_domain(model: AgentMessageModel) -> AgentMessage:
        return AgentMessage(
            id=model.id,
            project_id=model.project_id,
            user_id=model.user_id,
            root_message_id=getattr(model, "root_message_id", None),
            prompt=model.prompt,
            image_url=model.image_url,
            response_markdown=model.response_markdown,
            status=AgentMessageStatus(model.status),
            plan=model.plan,
            plan_version=model.plan_version,
            request_fingerprint=model.request_fingerprint,
            cancel_requested_at=model.cancel_requested_at,
            lease_owner=model.lease_owner,
            lease_expires_at=model.lease_expires_at,
            lease_heartbeat_at=model.lease_heartbeat_at,
            created_at=model.created_date,
        )
