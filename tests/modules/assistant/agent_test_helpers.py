"""Ayudantes para probar por separado la aceptación HTTP y el worker del agente."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.infrastructure.services.agent_runtime_factory import (
    build_process_agent_message_use_case,
)


def process_accepted_message(
    *, session: Session, project_id: UUID, user_id: str, message_id: UUID
) -> None:
    """Reclama y procesa un mensaje aceptado con el proveedor falso configurado por el test."""
    worker_id = f"test-worker-{uuid4()}"
    now = datetime.now(timezone.utc)
    repository = SQLModelAgentMessageRepository(session)
    claimed = repository.claim_next(
        worker_id=worker_id,
        now=now,
        lease_until=now + timedelta(seconds=60),
    )
    session.commit()
    assert claimed is not None and claimed.id == message_id

    processor = build_process_agent_message_use_case(
        session=session,
        project_id=project_id,
        user_id=user_id,
        message_id=message_id,
        worker_id=worker_id,
    )
    asyncio.run(
        processor.execute(
            message_id=message_id,
            project_id=project_id,
            user_id=user_id,
        )
    )


def process_and_fetch_message(
    *,
    client: TestClient,
    session: Session,
    project_id: UUID,
    user_id: str,
    accepted_response,
):
    """Procesa el UUID aceptado y consulta la proyección terminal persistida."""
    assert accepted_response.status_code == 202
    message_id = UUID(accepted_response.json()["message_id"])
    process_accepted_message(
        session=session,
        project_id=project_id,
        user_id=user_id,
        message_id=message_id,
    )
    return client.get(
        f"/api/projects/{project_id}/assistant/messages/{message_id}"
    )


class CountingAiProvider:
    """Proveedor AI instrumentalizado para verificar corte estricto de inferencias."""

    def __init__(
        self,
        responses: list[Any] | None = None,
        default_response: Any | None = None,
    ) -> None:
        self.responses: list[Any] = list(responses or [])
        self.default_response: Any = default_response
        self.requests: list[Any] = []
        self.complete_calls_count: int = 0

    async def complete(self, request: Any) -> Any:
        self.complete_calls_count += 1
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        if self.default_response is not None:
            return self.default_response
        from app.modules.assistant.application.ports.providers.ai_provider import (
            AiResult,
            ModelRole,
        )
        return AiResult(
            text="Respuesta por defecto de CountingAiProvider",
            model_role=ModelRole.MAIN,
            model="counting-fake",
            completed=True,
        )


class CountingToolRegistry:
    """Registro instrumentalizado para contar tool calls e inyectar excepciones de dominio."""

    def __init__(
        self,
        real_registry: Any = None,
        injected_exceptions: dict[str, Exception] | None = None,
        canned_results: dict[str, Any] | None = None,
    ) -> None:
        self.real_registry = real_registry
        self.injected_exceptions: dict[str, Exception] = dict(injected_exceptions or {})
        self.canned_results: dict[str, Any] = dict(canned_results or {})
        self.tool_calls_count: int = 0
        self.executed_calls: list[tuple[str, dict[str, Any]]] = []

    def inject_exception(self, tool_name: str, exception: Exception) -> None:
        self.injected_exceptions[tool_name] = exception

    def definitions_for_task(self, *, mutation_allowed: bool, **kwargs: Any) -> tuple[Any, ...]:
        if self.real_registry is not None:
            return self.real_registry.definitions_for_task(mutation_allowed=mutation_allowed, **kwargs)
        return ()

    def allowed_names_for_task(self, *, mutation_allowed: bool, **kwargs: Any) -> frozenset[str]:
        if self.real_registry is not None:
            return self.real_registry.allowed_names_for_task(mutation_allowed=mutation_allowed, **kwargs)
        return frozenset()

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        progress: Any | None = None,
        allowed_names: set[str] | None = None,
        visual_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.tool_calls_count += 1
        self.executed_calls.append((name, dict(arguments)))

        if name in self.injected_exceptions:
            exc = self.injected_exceptions[name]
            raise exc

        if name in self.canned_results:
            return self.canned_results[name]

        if self.real_registry is not None:
            return await self.real_registry.execute(
                name, arguments, progress, allowed_names=allowed_names, visual_scope=visual_scope
            )

        return {"status": "applied", "message": f"Tool {name} executed"}


class CountingUnitOfWork:
    """Unit of work instrumentalizado para verificar commits y rollbacks."""

    def __init__(self, real_uow: Any = None) -> None:
        self.real_uow = real_uow
        self.commits_count: int = 0
        self.rollbacks_count: int = 0

    def commit(self) -> None:
        self.commits_count += 1
        if self.real_uow is not None:
            self.real_uow.commit()

    def rollback(self) -> None:
        self.rollbacks_count += 1
        if self.real_uow is not None:
            self.real_uow.rollback()


class CountingCompletionPublisher:
    """Publicador de finalización instrumentalizado para registrar eventos terminales."""

    def __init__(self) -> None:
        self.published_events: list[dict[str, Any]] = []
        self.published_count: int = 0

    async def publish_finished(
        self,
        *,
        project_id: UUID,
        user_id: str,
        message_id: UUID,
        prompt: str,
        image_url: str | None,
        status: str,
        response_markdown: str,
        created_at: datetime,
        author_name: str | None = None,
        author_avatar_url: str | None = None,
    ) -> None:
        self.published_count += 1
        self.published_events.append(
            {
                "project_id": project_id,
                "user_id": user_id,
                "message_id": message_id,
                "prompt": prompt,
                "image_url": image_url,
                "status": status,
                "response_markdown": response_markdown,
                "created_at": created_at,
                "author_name": author_name,
                "author_avatar_url": author_avatar_url,
            }
        )

