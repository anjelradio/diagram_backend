"""Ejecución durable de mensajes aceptados, independiente de la petición HTTP."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlmodel import Session

from app.core.database import engine
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_continuation import ContinuationCloseReason
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_author_name_reader import (
    SQLModelAgentAuthorNameReader,
)
from app.modules.assistant.infrastructure.realtime.agent_completion_publisher import (
    WebSocketAgentCompletionPublisher,
)
from app.modules.assistant.infrastructure.services.agent_runtime_factory import (
    build_process_agent_message_use_case,
)

logger = logging.getLogger(__name__)


class AgentJobRunner:
    """Poller de un solo proceso con leases persistidos y recuperación segura."""

    LEASE_SECONDS = 90
    HEARTBEAT_SECONDS = 20
    POLL_SECONDS = 1
    MAX_CONCURRENCY = 4

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = lambda: Session(engine),
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id or f"assistant-{uuid4()}"
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._jobs: set[asyncio.Task[None]] = set()
        self._stopping = False

    async def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="agent-job-runner")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def notify(self, _message_id: UUID | None = None) -> None:
        """Despierta al poller; la base de datos, no el request, es la fuente de verdad."""
        self._wake.set()

    async def _run(self) -> None:
        try:
            while not self._stopping:
                while len(self._jobs) < self.MAX_CONCURRENCY and not self._stopping:
                    message = self._claim_next()
                    if message is None:
                        break
                    attempt_id = uuid4()
                    activity_stopped = asyncio.Event()
                    task = asyncio.create_task(
                        self._run_claimed(
                            message,
                            attempt_id=attempt_id,
                            activity_stopped=activity_stopped,
                        ),
                        name=f"agent-job-{message.id}",
                    )
                    self._jobs.add(task)

                self._wake.clear()
                wake_task = asyncio.create_task(self._wake.wait())
                waiters = {*self._jobs, wake_task}
                done, pending = await asyncio.wait(
                    waiters,
                    timeout=self.POLL_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    if task is wake_task:
                        continue
                    self._jobs.discard(task)
                    try:
                        await task
                    except asyncio.CancelledError:
                        if not self._stopping:
                            raise
                    except Exception:
                        logger.exception("Fallo inesperado en un job del asistente")
                for task in pending:
                    if task is wake_task:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            for job in self._jobs:
                job.cancel()
            await asyncio.gather(*self._jobs, return_exceptions=True)
            self._jobs.clear()
            raise

    def _claim_next(self) -> AgentMessage | None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            repository = SQLModelAgentMessageRepository(session)
            message = repository.claim_next(
                worker_id=self.worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self.LEASE_SECONDS),
            )
            session.commit()
            return message

    async def _run_claimed(
        self,
        message: AgentMessage,
        *,
        attempt_id: UUID | None = None,
        activity_stopped: asyncio.Event | None = None,
    ) -> None:
        attempt_id = attempt_id or uuid4()
        activity_stopped = activity_stopped or asyncio.Event()
        if _has_unreplayable_mutation_state(message.plan):
            await self._fail_uncertain_recovery(message)
            return

        process_task = asyncio.create_task(
            self._process(message, attempt_id, activity_stopped)
        )
        monitor_task = asyncio.create_task(self._monitor(message.id, process_task))
        try:
            done, _ = await asyncio.wait(
                {process_task, monitor_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if monitor_task in done:
                outcome = monitor_task.result()
                if process_task.done():
                    await process_task
                elif outcome == "cancel_requested":
                    activity_stopped.set()
                    process_task.cancel()
                    await asyncio.gather(process_task, return_exceptions=True)
                    await self._finalize_cancelled(message)
                elif outcome == "lease_lost":
                    activity_stopped.set()
                    process_task.cancel()
                    await asyncio.gather(process_task, return_exceptions=True)
            elif process_task in done:
                await process_task
        except asyncio.CancelledError:
            process_task.cancel()
            monitor_task.cancel()
            await asyncio.gather(process_task, monitor_task, return_exceptions=True)
            raise
        finally:
            activity_stopped.set()
            if not monitor_task.done():
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)

    async def _process(
        self,
        message: AgentMessage,
        attempt_id: UUID,
        activity_stopped: asyncio.Event,
    ) -> None:
        with self.session_factory() as session:
            process = build_process_agent_message_use_case(
                session=session,
                project_id=message.project_id,
                user_id=message.user_id,
                message_id=message.id,
                worker_id=self.worker_id,
                attempt_id=attempt_id,
                activity_stopped=activity_stopped,
            )
            await process.execute(
                message_id=message.id,
                project_id=message.project_id,
                user_id=message.user_id,
            )

    async def _monitor(
        self, message_id: UUID, process_task: asyncio.Task[None]
    ) -> str:
        while not process_task.done():
            await asyncio.sleep(self.HEARTBEAT_SECONDS)
            now = datetime.now(timezone.utc)
            with self.session_factory() as session:
                repository = SQLModelAgentMessageRepository(session)
                if repository.is_cancel_requested(message_id):
                    return "cancel_requested"
                renewed = repository.renew_lease(
                    message_id=message_id,
                    worker_id=self.worker_id,
                    now=now,
                    lease_until=now + timedelta(seconds=self.LEASE_SECONDS),
                )
                session.commit()
                if not renewed:
                    latest = repository.find_by_id(message_id)
                    if latest is None or latest.status is not AgentMessageStatus.RUNNING:
                        return "finished"
                    return "lease_lost"
        return "finished"

    async def _finalize_cancelled(self, claimed: AgentMessage) -> None:
        with self.session_factory() as session:
            repository = SQLModelAgentMessageRepository(session, worker_id=self.worker_id)
            message = repository.find_by_id(claimed.id)
            if message is None or message.status is not AgentMessageStatus.RUNNING:
                return
            message.cancel("La ejecución se canceló. Los cambios ya confirmados se conservan.")
            if not repository.save_terminal(message):
                session.rollback()
                return
            SQLModelAgentContinuationRepository(session).close_claimed_by_message(
                message_id=claimed.id,
                close_reason=ContinuationCloseReason.CANCELLED,
            )
            session.commit()
            profile = SQLModelAgentAuthorNameReader(session).find_profiles(
                {message.user_id}
            ).get(message.user_id)
        await WebSocketAgentCompletionPublisher().publish_finished(
            project_id=message.project_id,
            user_id=message.user_id,
            message_id=message.id,
            prompt=message.prompt,
            image_url=message.image_url,
            status=message.status.value,
            response_markdown=message.response_markdown or "La ejecución se canceló.",
            created_at=message.created_at,
            author_name=profile.name if profile and profile.name else message.user_id,
            author_avatar_url=profile.avatar_url if profile else None,
        )

    async def _fail_uncertain_recovery(self, claimed: AgentMessage) -> None:
        with self.session_factory() as session:
            repository = SQLModelAgentMessageRepository(session, worker_id=self.worker_id)
            message = repository.find_by_id(claimed.id)
            if message is None or message.status is not AgentMessageStatus.RUNNING:
                return
            message.fail(
                "La ejecución se interrumpió después de iniciar cambios. Conservé los cambios "
                "confirmados y no repetí operaciones cuyo resultado no puedo verificar. "
                "Revisa el diagrama antes de volver a solicitar esos cambios."
            )
            if not repository.save_terminal(message):
                session.rollback()
                return
            SQLModelAgentContinuationRepository(session).close_claimed_by_message(
                message_id=claimed.id,
                close_reason=ContinuationCloseReason.FAILED,
            )
            session.commit()
            profile = SQLModelAgentAuthorNameReader(session).find_profiles(
                {message.user_id}
            ).get(message.user_id)
        await WebSocketAgentCompletionPublisher().publish_finished(
            project_id=message.project_id,
            user_id=message.user_id,
            message_id=message.id,
            prompt=message.prompt,
            image_url=message.image_url,
            status=message.status.value,
            response_markdown=message.response_markdown or "La ejecución falló.",
            created_at=message.created_at,
            author_name=profile.name if profile and profile.name else message.user_id,
            author_avatar_url=profile.avatar_url if profile else None,
        )


def _has_unreplayable_mutation_state(plan: object) -> bool:
    if not isinstance(plan, dict):
        return False
    ledger = plan.get("operation_ledger")
    # El executor actual no puede rehidratar y continuar un plan ya iniciado.
    # Fallar cerrado ante cualquier operación evita duplicar commits previos.
    return isinstance(ledger, list) and bool(ledger)

