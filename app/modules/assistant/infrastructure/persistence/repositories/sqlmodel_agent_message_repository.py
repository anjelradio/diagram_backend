import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select, update

from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.exceptions import (
    AgentAlreadyActiveException,
    AgentMessageAlreadyExistsException,
)
from app.modules.assistant.domain.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from app.modules.assistant.application.services.visual.visual_clarification import (
    is_valid_visual_clarification,
)
from app.modules.assistant.infrastructure.persistence.mappers.agent_message_mapper import (
    AgentMessageMapper,
)
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)


class SQLModelAgentMessageRepository(AgentMessageRepository):
    """Guarda mensajes y resuelve la carrera del único estado running."""

    _SQLITE_LOCK_RETRIES = 3

    def __init__(self, session: Session, *, worker_id: str | None = None) -> None:
        self.session = session
        self.worker_id = worker_id

    def find_by_id(self, message_id: UUID) -> AgentMessage | None:
        statement = select(AgentMessageModel).where(
            AgentMessageModel.id == message_id,
            AgentMessageModel.deleted_date.is_(None),
        )
        record = self.session.exec(statement).first()
        return AgentMessageMapper.to_domain(record) if record is not None else None

    def save_new(self, message: AgentMessage) -> None:
        if self.session.get(AgentMessageModel, message.id) is not None:
            raise AgentMessageAlreadyExistsException()

        running_statement = select(AgentMessageModel.id).where(
            AgentMessageModel.project_id == message.project_id,
            AgentMessageModel.user_id == message.user_id,
            AgentMessageModel.status == "running",
            AgentMessageModel.deleted_date.is_(None),
        )
        if message.status.value != "running":
            raise AgentAlreadyActiveException()
        for attempt in range(self._SQLITE_LOCK_RETRIES + 1):
            try:
                running_exists = self.session.exec(running_statement).first() is not None
                break
            except OperationalError as exc:
                if not self._is_sqlite_lock(exc) or attempt >= self._SQLITE_LOCK_RETRIES:
                    raise
                time.sleep(0.025 * (attempt + 1))
        if running_exists:
            raise AgentAlreadyActiveException()

        for attempt in range(self._SQLITE_LOCK_RETRIES + 1):
            savepoint = self.session.begin_nested()
            self.session.add(AgentMessageMapper.to_model(message))
            try:
                self.session.flush()
                savepoint.commit()
                return
            except IntegrityError as exc:
                savepoint.rollback()
                if (
                    message.status.value == "running"
                    and self._is_running_index_conflict(exc)
                ):
                    raise AgentAlreadyActiveException() from exc
                if self._is_primary_key_conflict(exc):
                    raise AgentMessageAlreadyExistsException() from exc
                raise
            except OperationalError as exc:
                savepoint.rollback()
                if not self._is_sqlite_lock(exc) or attempt >= self._SQLITE_LOCK_RETRIES:
                    raise
                time.sleep(0.025 * (attempt + 1))

    def claim_next(self, *, worker_id: str, now: datetime, lease_until: datetime) -> AgentMessage | None:
        candidates = self.session.exec(
            select(AgentMessageModel.id)
            .where(
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
                or_(AgentMessageModel.lease_expires_at.is_(None), AgentMessageModel.lease_expires_at <= now),
            )
            .order_by(AgentMessageModel.created_date, AgentMessageModel.id)
            .limit(20)
        ).all()
        for message_id in candidates:
            statement = (
                update(AgentMessageModel)
                .where(
                    AgentMessageModel.id == message_id,
                    AgentMessageModel.status == "running",
                    AgentMessageModel.deleted_date.is_(None),
                    or_(AgentMessageModel.lease_expires_at.is_(None), AgentMessageModel.lease_expires_at <= now),
                )
                .values(lease_owner=worker_id, lease_expires_at=lease_until, lease_heartbeat_at=now)
            )
            if self.session.execute(statement).rowcount == 1:
                self.session.flush()
                return self.find_by_id(message_id)
        return None

    def renew_lease(self, *, message_id: UUID, worker_id: str, now: datetime, lease_until: datetime) -> bool:
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.lease_owner == worker_id,
                AgentMessageModel.deleted_date.is_(None),
            )
            .values(lease_expires_at=lease_until, lease_heartbeat_at=now)
        )
        return self.session.execute(statement).rowcount == 1

    def is_cancel_requested(self, message_id: UUID) -> bool:
        value = self.session.exec(
            select(AgentMessageModel.cancel_requested_at).where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
            )
        ).first()
        return value is not None

    def request_cancel(self, *, message_id: UUID, project_id: UUID, user_id: str, now: datetime) -> AgentMessage | None:
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
                AgentMessageModel.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=now, modified_date=now)
        )
        self.session.execute(statement)
        self.session.flush()
        record = self.session.exec(
            select(AgentMessageModel).where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
            )
        ).first()
        return AgentMessageMapper.to_domain(record) if record is not None else None

    def get_active_for_user(self, *, project_id: UUID, user_id: str) -> AgentMessage | None:
        record = self.session.exec(
            select(AgentMessageModel).where(
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
            ).limit(1)
        ).first()
        return AgentMessageMapper.to_domain(record) if record is not None else None

    def list_for_project(self, *, project_id: UUID, limit: int, offset: int, snapshot_at: datetime) -> list[AgentMessage]:
        records = self.session.exec(
            select(AgentMessageModel)
            .where(
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.created_date <= snapshot_at,
                AgentMessageModel.deleted_date.is_(None),
            )
            .order_by(AgentMessageModel.created_date.desc(), AgentMessageModel.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [AgentMessageMapper.to_domain(record) for record in records]

    def save_terminal(self, message: AgentMessage) -> bool:
        if message.status.value not in {"completed", "partial", "failed", "cancelled"}:
            return False
        if (
            not isinstance(message.response_markdown, str)
            or not message.response_markdown.strip()
        ):
            return False
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message.id,
                AgentMessageModel.status == "running",
                AgentMessageModel.plan_version == message.plan_version,
                AgentMessageModel.deleted_date.is_(None),
                *([AgentMessageModel.lease_owner == self.worker_id] if self.worker_id else []),
            )
            .values(
                status=message.status.value,
                response_markdown=message.response_markdown,
                plan=message.plan,
                root_message_id=message.root_message_id,
                lease_owner=None,
                lease_expires_at=None,
                lease_heartbeat_at=None,
            )
        )
        result = self.session.execute(statement)
        return result.rowcount == 1

    def link_root_message(self, *, message_id: UUID, root_message_id: UUID) -> bool:
        """Asocia un mensaje a su mensaje raíz dentro del mismo hilo."""
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.status == "running",
                AgentMessageModel.deleted_date.is_(None),
                *([AgentMessageModel.lease_owner == self.worker_id] if self.worker_id else []),
            )
            .values(
                root_message_id=root_message_id,
                modified_date=datetime.now(timezone.utc),
            )
        )
        return self.session.execute(statement).rowcount == 1

    def save_plan_progress(self, message: AgentMessage) -> bool:
        """Persiste avance de plan solo si el mensaje sigue en la versión leída."""
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message.id,
                AgentMessageModel.status == "running",
                AgentMessageModel.plan_version == message.plan_version,
                AgentMessageModel.deleted_date.is_(None),
                *([AgentMessageModel.lease_owner == self.worker_id] if self.worker_id else []),
            )
            .values(
                plan=message.plan,
                plan_version=message.plan_version + 1,
                modified_date=datetime.now(timezone.utc),
            )
        )
        result = self.session.execute(statement)
        if result.rowcount != 1:
            return False
        message.plan_version += 1
        return True

    def image_url_is_referenced(self, message_id: UUID, image_url: str) -> bool | None:
        try:
            statement = select(AgentMessageModel.id).where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.image_url == image_url,
            )
            return self.session.exec(statement).first() is not None
        except Exception:
            return None

    def find_pending_visual_clarifications(
        self, *, user_id: str, project_id: UUID
    ) -> list[AgentMessage]:
        statement = (
            select(AgentMessageModel)
            .where(
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "completed",
                AgentMessageModel.deleted_date.is_(None),
            )
            .order_by(AgentMessageModel.created_date.desc())
            .limit(50)
        )
        messages = []
        for record in self.session.exec(statement).all():
            if (
                isinstance(record.plan, dict)
                and record.plan.get("kind") == "visual_clarification"
                and record.plan.get("claimed_by") is None
            ):
                messages.append(AgentMessageMapper.to_domain(record))
        return messages

    def claim_visual_clarification(
        self,
        *,
        message_id: UUID,
        expected_version: int,
        continuation_id: UUID,
        user_id: str,
        project_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        record = self.session.exec(
            select(AgentMessageModel).where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "completed",
                AgentMessageModel.plan_version == expected_version,
                AgentMessageModel.deleted_date.is_(None),
            )
        ).first()
        if record is None or not is_valid_visual_clarification(
            record.plan,
            user_id=user_id,
            project_id=project_id,
            now=now,
        ):
            return False
        claimed_plan = {**record.plan, "claimed_by": str(continuation_id)}
        statement = (
            update(AgentMessageModel)
            .where(
                AgentMessageModel.id == message_id,
                AgentMessageModel.project_id == project_id,
                AgentMessageModel.user_id == user_id,
                AgentMessageModel.status == "completed",
                AgentMessageModel.plan_version == expected_version,
                AgentMessageModel.plan == record.plan,
                AgentMessageModel.deleted_date.is_(None),
            )
            .values(
                plan=claimed_plan,
                plan_version=expected_version + 1,
                modified_date=datetime.now(timezone.utc),
            )
        )
        return self.session.execute(statement).rowcount == 1

    @staticmethod
    def _constraint_name(exc: IntegrityError) -> str:
        return str(getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or "")

    @classmethod
    def _is_running_index_conflict(cls, exc: IntegrityError) -> bool:
        if cls._constraint_name(exc) == "uq_agent_messages_running_project_user":
            return True
        message = str(exc.orig).lower()
        return (
            "unique constraint failed: agent_messages.project_id, agent_messages.user_id"
            in message
        )

    @classmethod
    def _is_primary_key_conflict(cls, exc: IntegrityError) -> bool:
        if cls._constraint_name(exc) in {"agent_messages_pkey", "pk_agent_messages"}:
            return True
        message = str(exc.orig).lower()
        return "agent_messages.id" in message or "agent_messages_pkey" in message

    @staticmethod
    def _is_sqlite_lock(exc: OperationalError) -> bool:
        message = str(exc.orig).lower()
        return "database is locked" in message or "database is busy" in message
