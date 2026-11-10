"""Pruebas de persistencia para SQLModelAgentContinuationRepository."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_continuation_repository import (
    SQLModelAgentContinuationRepository,
)
from app.modules.assistant.infrastructure.persistence.repositories.sqlmodel_agent_message_repository import (
    SQLModelAgentMessageRepository,
)
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def _create_message(session: Session, project_id, user_id="user_owner") -> AgentMessage:
    repo = SQLModelAgentMessageRepository(session)
    msg = AgentMessage.register(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Test prompt",
    )
    repo.save_new(msg)
    terminal_msg = AgentMessage(
        id=msg.id,
        project_id=msg.project_id,
        user_id=msg.user_id,
        prompt=msg.prompt,
        status=AgentMessageStatus.COMPLETED,
        response_markdown="Terminado",
        created_at=msg.created_at,
    )
    repo.save_terminal(terminal_msg)
    session.commit()
    return terminal_msg


def test_continuation_repository_save_find_and_filters(
    session: Session, test_project: ProjectModel
):
    repo = SQLModelAgentContinuationRepository(session)
    msg1 = _create_message(session, test_project.id, user_id="user_owner")
    msg2 = _create_message(session, test_project.id, user_id="user_other")

    c1 = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        root_message_id=msg1.id,
        effective_request="Petición 1",
        missing_fields=[{"key": "campo", "question": "¿Dato?"}],
    )
    repo.save(c1)

    c2 = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_other",
        root_message_id=msg2.id,
        effective_request="Petición otro usuario",
    )
    repo.save(c2)
    session.commit()

    # Buscar por id
    loaded = repo.find_by_id(c1.id)
    assert loaded is not None
    assert loaded.id == c1.id
    assert loaded.user_id == "user_owner"
    assert loaded.effective_request == "Petición 1"

    # Buscar por root_message_id
    by_root = repo.find_by_root_message_id(msg1.id)
    assert by_root is not None
    assert by_root.id == c1.id

    # Filtro usuario y proyecto
    candidates_owner = repo.list_active_candidates(
        project_id=test_project.id, user_id="user_owner"
    )
    assert len(candidates_owner) == 1
    assert candidates_owner[0].id == c1.id

    candidates_other = repo.list_active_candidates(
        project_id=test_project.id, user_id="user_other"
    )
    assert len(candidates_other) == 1
    assert candidates_other[0].id == c2.id


def test_continuation_repository_ttl_and_limit_three_candidates(
    session: Session, test_project: ProjectModel
):
    repo = SQLModelAgentContinuationRepository(session)
    user_id = "user_owner"
    now = datetime.now(timezone.utc)

    # Crear 4 continuaciones abiertas de tipo reintento residual; 1 de ellas expirada
    for i in range(4):
        msg = _create_message(session, test_project.id, user_id=user_id)
        is_expired = i == 0
        expires = now - timedelta(hours=1) if is_expired else now + timedelta(hours=24)
        c = AgentContinuation.create(
            id=uuid4(),
            project_id=test_project.id,
            user_id=user_id,
            root_message_id=msg.id,
            effective_request=f"Petición {i}",
            purpose=ContinuationPurpose.RESIDUAL_RETRY,
            expires_at=expires,
        )
        repo.save(c)
    session.commit()

    # Listar candidatos: debe excluir la expirada y respetar el límite máximo de 3
    candidates = repo.list_active_candidates(
        project_id=test_project.id, user_id=user_id, limit=3, now=now
    )
    assert len(candidates) == 3
    for cand in candidates:
        assert cand.effective_request != "Petición 0"


def test_continuation_repository_single_clarification_thread_uniqueness_and_expire_stale(
    session: Session, test_project: ProjectModel
):
    """Verifica que para aclaraciones solo existe un hilo activo por usuario y proyecto,
    y que al guardar una nueva aclaración activa se expira automáticamente la anterior."""
    repo = SQLModelAgentContinuationRepository(session)
    user_id = "user_single_thread"

    msg1 = _create_message(session, test_project.id, user_id=user_id)
    c1 = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_id,
        root_message_id=msg1.id,
        effective_request="Primera aclaración",
        missing_fields=[{"key": "type", "critical": True}],
    )
    repo.save(c1)
    session.commit()

    active = repo.find_active_by_scope(project_id=test_project.id, user_id=user_id)
    assert active is not None
    assert active.id == c1.id
    assert active.state == ContinuationState.AWAITING_INPUT

    msg2 = _create_message(session, test_project.id, user_id=user_id)
    c2 = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_id,
        root_message_id=msg2.id,
        effective_request="Segunda aclaración nueva",
        missing_fields=[{"key": "cardinality", "critical": True}],
    )
    repo.save(c2)
    session.commit()

    # La anterior debe haber quedado expirada
    c1_reloaded = repo.find_by_id(c1.id)
    assert c1_reloaded.state == ContinuationState.EXPIRED
    assert c1_reloaded.close_reason == "expired"

    # La activa actual debe ser la segunda
    current_active = repo.find_active_by_scope(project_id=test_project.id, user_id=user_id)
    assert current_active is not None
    assert current_active.id == c2.id
    assert current_active.state == ContinuationState.AWAITING_INPUT


def test_continuation_repository_atomic_cas_claim(
    session: Session, test_project: ProjectModel
):
    repo = SQLModelAgentContinuationRepository(session)
    msg = _create_message(session, test_project.id, user_id="user_owner")
    consumer_msg = _create_message(session, test_project.id, user_id="user_owner")

    c = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        root_message_id=msg.id,
        effective_request="Petición para claim",
    )
    repo.save(c)
    session.commit()

    # Claim con versión correcta
    claimed = repo.claim_atomic(
        continuation_id=c.id,
        expected_version=1,
        by_message_id=consumer_msg.id,
    )
    assert claimed is not None
    assert claimed.state == ContinuationState.CLAIMED
    assert claimed.version == 2
    assert claimed.claimed_by_message_id == consumer_msg.id
    session.commit()

    # Reintentar con versión vieja (versión 1) retorna None
    failed_claim = repo.claim_atomic(
        continuation_id=c.id,
        expected_version=1,
        by_message_id=uuid4(),
    )
    assert failed_claim is None

    # Idempotencia: el mismo consumidor que ya reclamó puede recuperar la continuación reclamada
    same_consumer_claim = repo.claim_atomic(
        continuation_id=c.id,
        expected_version=2,
        by_message_id=consumer_msg.id,
    )
    assert same_consumer_claim is not None
    assert same_consumer_claim.claimed_by_message_id == consumer_msg.id

    # Rechazo de un segundo reclamante distinto cuando ya está reclamada
    other_msg = _create_message(session, test_project.id, user_id="user_owner")
    other_claim = repo.claim_atomic(
        continuation_id=c.id,
        expected_version=2,
        by_message_id=other_msg.id,
    )
    assert other_claim is None


def test_continuation_resolve_atomic_with_close_reasons(
    session: Session, test_project: ProjectModel
):
    repo = SQLModelAgentContinuationRepository(session)
    msg = _create_message(session, test_project.id, user_id="user_owner")
    consumer_msg = _create_message(session, test_project.id, user_id="user_owner")

    c = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id="user_owner",
        root_message_id=msg.id,
        effective_request="Petición para resolver",
    )
    repo.save(c)
    session.commit()

    # Reclamar primero
    claimed = repo.claim_atomic(
        continuation_id=c.id,
        expected_version=1,
        by_message_id=consumer_msg.id,
    )
    assert claimed is not None

    # Intentar resolver con versión incorrecta
    bad_resolve = repo.resolve_atomic(
        continuation_id=c.id,
        expected_version=1,
        outcome=ContinuationOutcome.SUCCESS,
        close_reason=ContinuationCloseReason.RESOLVED,
    )
    assert bad_resolve is None

    # Resolver con versión correcta y close_reason
    resolved = repo.resolve_atomic(
        continuation_id=c.id,
        expected_version=2,
        outcome=ContinuationOutcome.SUCCESS,
        close_reason=ContinuationCloseReason.RESOLVED,
    )
    assert resolved is not None
    assert resolved.state == ContinuationState.RESOLVED
    assert resolved.close_reason == ContinuationCloseReason.RESOLVED
    assert resolved.version == 3

    # Ya no debe aparecer como hilo activo
    active = repo.find_active_by_scope(project_id=test_project.id, user_id="user_owner")
    assert active is None


def test_find_active_by_scope_filters_purpose_and_user_isolation(
    session: Session, test_project: ProjectModel
):
    repo = SQLModelAgentContinuationRepository(session)
    user_a = "user_a"
    user_b = "user_b"

    msg_a = _create_message(session, test_project.id, user_id=user_a)
    msg_b = _create_message(session, test_project.id, user_id=user_b)

    # user_a tiene un hilo de aclaración
    c_clarif = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_a,
        root_message_id=msg_a.id,
        effective_request="Aclaración user_a",
        purpose=ContinuationPurpose.CLARIFICATION,
    )
    repo.save(c_clarif)

    # user_a también tiene un reintento residual
    c_residual = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_a,
        root_message_id=msg_a.id,
        effective_request="Reintento user_a",
        purpose=ContinuationPurpose.RESIDUAL_RETRY,
    )
    repo.save(c_residual)

    # user_b tiene una aclaración
    c_b = AgentContinuation.create(
        id=uuid4(),
        project_id=test_project.id,
        user_id=user_b,
        root_message_id=msg_b.id,
        effective_request="Aclaración user_b",
        purpose=ContinuationPurpose.CLARIFICATION,
    )
    repo.save(c_b)
    session.commit()

    # find_active_by_scope para user_a debe devolver SOLO la aclaración de user_a
    active_a = repo.find_active_by_scope(project_id=test_project.id, user_id=user_a)
    assert active_a is not None
    assert active_a.id == c_clarif.id
    assert active_a.purpose == ContinuationPurpose.CLARIFICATION

    # find_active_by_scope para user_b debe devolver la de user_b
    active_b = repo.find_active_by_scope(project_id=test_project.id, user_id=user_b)
    assert active_b is not None
    assert active_b.id == c_b.id
