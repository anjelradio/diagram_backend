"""Pruebas de aislamiento, expiración, rechazo y no-claim en ambigüedad (US3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
    ResolutionDecision,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
    ContinuationOutcome,
)
from tests.modules.assistant.test_process_agent_message_continuation import (
    InMemoryContinuationRepository,
)


def _create_continuation(
    *,
    project_id: UUID,
    user_id: str,
    effective_request: str = "Test",
    expires_at: datetime | None = None,
) -> AgentContinuation:
    return AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=uuid4(),
        effective_request=effective_request,
        expires_at=expires_at,
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_project_isolation_does_not_consume_continuation_from_other_project():
    """Un mensaje en el Proyecto B no debe resolver ni reclamar una continuación del Proyecto A."""
    proj_a = uuid4()
    proj_b = uuid4()
    user_id = "user-123"

    repo = InMemoryContinuationRepository()
    cont_a = _create_continuation(
        project_id=proj_a,
        user_id=user_id,
        effective_request="Relaciona Producto con Categoría",
    )
    cont_a = cont_a.apply_clarification(
        new_effective_request="Relaciona Producto con Categoría",
        resolved_facts=[],
        remaining_missing_fields=[{"key": "relation.type"}],
        latest_message_id=uuid4(),
    )
    repo.save(cont_a)

    # Buscar candidatos en Proyecto B
    candidates_b = repo.list_active_candidates(project_id=proj_b, user_id=user_id)
    assert len(candidates_b) == 0

    resolver = ContinuationResolver(ai_provider=None)
    resolution = await resolver.resolve(user_prompt="asociación", candidates=candidates_b)

    assert resolution.decision == ResolutionDecision.NEW_REQUEST
    assert resolution.candidate_id is None

    # La continuación en Proyecto A permanece intacta
    persisted_a = repo.find_by_id(cont_a.id)
    assert persisted_a.state == ContinuationState.AWAITING_INPUT
    assert persisted_a.version == cont_a.version


@pytest.mark.anyio
async def test_user_isolation_does_not_consume_other_user_continuation():
    """Un usuario B en el mismo proyecto no puede consumir la continuación del usuario A."""
    proj_id = uuid4()
    user_a = "user-a"
    user_b = "user-b"

    repo = InMemoryContinuationRepository()
    cont_a = _create_continuation(
        project_id=proj_id,
        user_id=user_a,
        effective_request="Crear atributo en Factura",
    )
    repo.save(cont_a)

    candidates_b = repo.list_active_candidates(project_id=proj_id, user_id=user_b)
    assert len(candidates_b) == 0


@pytest.mark.anyio
async def test_expired_continuation_is_not_active_candidate():
    """Una continuación con más de 24 horas transcurridas expira y no se entrega como candidata."""
    proj_id = uuid4()
    user_id = "user-exp"
    repo = InMemoryContinuationRepository()

    now = datetime.now(timezone.utc)
    cont = _create_continuation(
        project_id=proj_id,
        user_id=user_id,
        expires_at=now - timedelta(seconds=1),
    )
    repo.save(cont)

    active = repo.list_active_candidates(project_id=proj_id, user_id=user_id, now=now)
    assert len(active) == 0


@pytest.mark.anyio
async def test_explicit_decline_marks_continuation_declined():
    """Un rechazo explícito ('no, cancela eso') cierra la continuación sin ejecutar cambios."""
    proj_id = uuid4()
    user_id = "user-dec"
    cont = _create_continuation(
        project_id=proj_id,
        user_id=user_id,
        effective_request="Crear clase Producto",
    )
    resolver = ContinuationResolver(ai_provider=None)
    resolution = await resolver.resolve(user_prompt="cancelar", candidates=[cont])

    assert resolution.decision == ResolutionDecision.DECLINE
    assert resolution.candidate_id == cont.id

    declined = cont.decline()
    assert declined.state == ContinuationState.DECLINED


@pytest.mark.anyio
async def test_ambiguous_prompt_with_multiple_candidates_does_not_claim():
    """Ante múltiples candidatos y una respuesta ambigua, no se reclama ninguno ni se incrementa la versión."""
    proj_id = uuid4()
    user_id = "user-multi"
    cont1 = _create_continuation(
        project_id=proj_id,
        user_id=user_id,
        effective_request="Relacionar Factura con Cliente",
    )
    cont2 = _create_continuation(
        project_id=proj_id,
        user_id=user_id,
        effective_request="Crear atributo importe en Pedido",
    )

    resolver = ContinuationResolver(ai_provider=None)
    resolution = await resolver.resolve(
        user_prompt="sí, hazlo",
        candidates=[cont1, cont2],
    )

    assert resolution.decision == ResolutionDecision.AMBIGUOUS
    assert resolution.candidate_id is None
    # No se filtran UUIDs en el mensaje
    assert resolution.ambiguity_message is not None
    assert str(cont1.id) not in resolution.ambiguity_message
    assert str(cont2.id) not in resolution.ambiguity_message
    # Ninguna versión cambia
    assert cont1.version == 1
    assert cont2.version == 1
