"""Pruebas unitarias para lectura y construcción de evidencia conversacional reciente."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    RecentExchange,
)
from app.modules.assistant.application.services.continuation.recent_conversation_evidence import (
    RecentConversationEvidenceBuilder,
)
from app.modules.assistant.infrastructure.persistence.models.agent_continuation_model import (
    AgentContinuationModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_conversation_reader import (
    SQLModelAgentConversationReader,
)


@pytest.fixture
def memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_get_recent_exchanges_filters_and_order(memory_session: Session):
    reader = SQLModelAgentConversationReader(memory_session)
    project_id = uuid4()
    other_project_id = uuid4()
    user_id = "user_1"
    other_user_id = "user_2"

    now = datetime.now(timezone.utc)

    # 1. Mensaje antiguo válido
    m1 = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crear clase Usuario",
        response_markdown="Clase Usuario creada exitosamente",
        status="completed",
        created_date=now - timedelta(minutes=30),
    )
    # 2. Mensaje medio válido
    m2 = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Agregar atributo email a Usuario",
        response_markdown="Atributo email agregado",
        status="completed",
        created_date=now - timedelta(minutes=20),
    )
    # 3. Mensaje más reciente válido
    m3 = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crear clase Perfil",
        response_markdown="Clase Perfil creada",
        status="completed",
        created_date=now - timedelta(minutes=10),
    )
    # 4. Mensaje de otro usuario (debe filtrarse)
    m_other_user = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=other_user_id,
        prompt="Mensaje de otro usuario",
        response_markdown="Respuesta a otro usuario",
        status="completed",
        created_date=now - timedelta(minutes=5),
    )
    # 5. Mensaje de otro proyecto (debe filtrarse)
    m_other_proj = AgentMessageModel(
        id=uuid4(),
        project_id=other_project_id,
        user_id=user_id,
        prompt="Mensaje en otro proyecto",
        response_markdown="Respuesta en otro proyecto",
        status="completed",
        created_date=now - timedelta(minutes=5),
    )
    # 6. Mensaje eliminado (debe filtrarse)
    m_deleted = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Mensaje eliminado",
        response_markdown="Respuesta eliminada",
        status="completed",
        deleted_date=now,
        created_date=now - timedelta(minutes=2),
    )
    # 7. Mensaje no completado (running/queued, debe filtrarse)
    m_running = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Mensaje en curso",
        response_markdown="En proceso...",
        status="running",
        created_date=now - timedelta(minutes=1),
    )

    memory_session.add_all([m1, m2, m3, m_other_user, m_other_proj, m_deleted, m_running])
    memory_session.commit()

    # Consulta básica
    exchanges = reader.get_recent_exchanges(
        project_id=project_id,
        user_id=user_id,
        limit=3,
    )

    assert len(exchanges) == 3
    # Verificamos orden descendente por fecha (más reciente primero)
    assert exchanges[0].message_id == m3.id
    assert exchanges[1].message_id == m2.id
    assert exchanges[2].message_id == m1.id

    # Exclusión de mensaje actual
    exchanges_excl = reader.get_recent_exchanges(
        project_id=project_id,
        user_id=user_id,
        exclude_message_id=m3.id,
        limit=3,
    )
    assert len(exchanges_excl) == 2
    assert exchanges_excl[0].message_id == m2.id
    assert exchanges_excl[1].message_id == m1.id

    # Filtro before
    exchanges_before = reader.get_recent_exchanges(
        project_id=project_id,
        user_id=user_id,
        before=now - timedelta(minutes=15),
        limit=3,
    )
    assert len(exchanges_before) == 2
    assert exchanges_before[0].message_id == m2.id
    assert exchanges_before[1].message_id == m1.id


def test_evidence_builder_prioritizes_recency_and_presents_chronologically():
    builder = RecentConversationEvidenceBuilder()
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    e1 = RecentExchange(
        message_id=uuid4(),
        created_at=t0,
        user_prompt="Pregunta 1",
        assistant_response="Respuesta 1",
    )
    e2 = RecentExchange(
        message_id=uuid4(),
        created_at=t0 + timedelta(minutes=5),
        user_prompt="Pregunta 2",
        assistant_response="Respuesta 2",
        confirmed_operations=("CREATE_CLASS(User)",),
    )
    e3 = RecentExchange(
        message_id=uuid4(),
        created_at=t0 + timedelta(minutes=10),
        user_prompt="Pregunta 3",
        assistant_response="Respuesta 3",
    )

    # Viene ordenado de más reciente a más antiguo: e3, e2, e1
    evidence = builder.build_evidence([e3, e2, e1], max_tokens=1500)

    # Debe presentarse cronológicamente: e1, e2, e3
    assert len(evidence) == 3
    assert evidence[0]["user"] == "Pregunta 1"
    assert evidence[1]["user"] == "Pregunta 2"
    assert evidence[1]["confirmed_operations"] == "CREATE_CLASS(User)"
    assert evidence[2]["user"] == "Pregunta 3"


def test_evidence_builder_respects_token_budget_without_dropping_most_recent():
    builder = RecentConversationEvidenceBuilder()
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    # Intercambio grande más antiguo
    e_old = RecentExchange(
        message_id=uuid4(),
        created_at=t0,
        user_prompt="Viejo " * 500,
        assistant_response="Respuesta " * 500,
    )
    # Intercambio reciente pequeño
    e_new = RecentExchange(
        message_id=uuid4(),
        created_at=t0 + timedelta(minutes=5),
        user_prompt="Pregunta reciente",
        assistant_response="Respuesta reciente",
    )

    # Con presupuesto ajustado, solo el más reciente debe caber
    evidence = builder.build_evidence([e_new, e_old], max_tokens=100)
    assert len(evidence) == 1
    assert evidence[0]["user"] == "Pregunta reciente"


def test_reader_identifies_and_excludes_superseded_exchanges(memory_session: Session):
    reader = SQLModelAgentConversationReader(memory_session)
    project_id = uuid4()
    user_id = "user_sup"
    now = datetime.now(timezone.utc)

    # 1. Mensaje que perteneció a un hilo sustituido por topic_change
    m_superseded = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crea relación entre A y B",
        response_markdown="¿Qué cardinalidades?",
        status="completed",
        created_date=now - timedelta(minutes=10),
    )
    cont_superseded = AgentContinuationModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=m_superseded.id,
        latest_message_id=m_superseded.id,
        effective_request="Crea relación entre A y B",
        purpose="clarification",
        state="declined",
        close_reason="topic_change",
        version=1,
        expires_at=now + timedelta(hours=1),
    )

    # 2. Mensaje completado regular válido
    m_valid = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt="Crea clase Cliente",
        response_markdown="Clase Cliente creada",
        status="completed",
        created_date=now - timedelta(minutes=5),
    )

    memory_session.add_all([m_superseded, cont_superseded, m_valid])
    memory_session.commit()

    # Sin exclude_superseded: devuelve ambos pero marca is_superseded
    all_exchanges = reader.get_recent_exchanges(
        project_id=project_id,
        user_id=user_id,
        limit=3,
        exclude_superseded=False,
    )
    assert len(all_exchanges) == 2
    sup_ex = next(e for e in all_exchanges if e.message_id == m_superseded.id)
    valid_ex = next(e for e in all_exchanges if e.message_id == m_valid.id)
    assert sup_ex.is_superseded is True
    assert valid_ex.is_superseded is False

    # Con exclude_superseded=True: el mensaje sustituido queda excluido
    active_exchanges = reader.get_recent_exchanges(
        project_id=project_id,
        user_id=user_id,
        limit=3,
        exclude_superseded=True,
    )
    assert len(active_exchanges) == 1
    assert active_exchanges[0].message_id == m_valid.id


def test_evidence_builder_ignores_superseded_exchanges():
    builder = RecentConversationEvidenceBuilder()
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    e_superseded = RecentExchange(
        message_id=uuid4(),
        created_at=t0,
        user_prompt="Mensaje sustituido",
        assistant_response="Respuesta previa",
        is_superseded=True,
    )
    e_valid = RecentExchange(
        message_id=uuid4(),
        created_at=t0 + timedelta(minutes=5),
        user_prompt="Mensaje válido",
        assistant_response="Respuesta válida",
        is_superseded=False,
    )

    # build_evidence debe omitir intercambios con is_superseded=True
    evidence = builder.build_evidence([e_valid, e_superseded], max_tokens=1500)
    assert len(evidence) == 1
    assert evidence[0]["user"] == "Mensaje válido"


def test_evidence_builder_truncation_when_exceeding_budget():
    """T013 / US2: Si los intercambios superan el presupuesto (1500 tokens),
    se descartan los más antiguos para priorizar recencia y no superar el límite."""
    builder = RecentConversationEvidenceBuilder()
    now = datetime.now(timezone.utc)

    # Turno reciente pero moderado
    recent_ex = RecentExchange(
        message_id=uuid4(),
        created_at=now,
        user_prompt="¿Qué relación recomiendas entre Factura y Detalle?",
        assistant_response="Te recomiendo Composición.",
        is_superseded=False,
    )
    # Turno antiguo gigante que excede los 1500 tokens
    huge_text = "explicación detallada con datos extensos " * 400  # ~2400 tokens
    old_huge_ex = RecentExchange(
        message_id=uuid4(),
        created_at=now - timedelta(minutes=10),
        user_prompt="Pregunta antigua",
        assistant_response=huge_text,
        is_superseded=False,
    )

    evidence = builder.build_evidence([recent_ex, old_huge_ex], max_tokens=1500)
    # Debe incluir solo el turno reciente y descartar el antiguo por presupuesto
    assert len(evidence) == 1
    assert evidence[0]["user"] == "¿Qué relación recomiendas entre Factura y Detalle?"


def test_reader_rejects_cross_user_and_cross_project_isolation(memory_session: Session):
    """T013 / US2: Comprueba aislamiento estricto por usuario y proyecto en el lector."""
    reader = SQLModelAgentConversationReader(memory_session)
    project_a = uuid4()
    project_b = uuid4()
    user_alice = "user_alice"
    user_bob = "user_bob"
    now = datetime.now(timezone.utc)

    m_bob = AgentMessageModel(
        id=uuid4(),
        project_id=project_a,
        user_id=user_bob,
        prompt="Mensaje privado de Bob",
        response_markdown="Respuesta a Bob",
        status="completed",
        created_date=now - timedelta(minutes=1),
    )
    m_proj_b = AgentMessageModel(
        id=uuid4(),
        project_id=project_b,
        user_id=user_alice,
        prompt="Mensaje de Alice en Proyecto B",
        response_markdown="Respuesta en Proyecto B",
        status="completed",
        created_date=now - timedelta(minutes=2),
    )
    memory_session.add_all([m_bob, m_proj_b])
    memory_session.commit()

    # Alice en Proyecto A no debe ver nada de Bob ni del Proyecto B
    exchanges = reader.get_recent_exchanges(
        project_id=project_a,
        user_id=user_alice,
        limit=5,
    )
    assert len(exchanges) == 0

