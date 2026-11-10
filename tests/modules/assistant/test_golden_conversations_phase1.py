"""Corpus dorado de conversaciones canónicas para la Fase 1 del pipeline por fases.

Casos evaluados:
1. "herencia" seco tras pregunta de tipo de relación.
2. "sí, continúa" cuando faltan campos (no debe saltarse la validación).
3. "sí, continúa y además crea la clase Árbol" (compuesto: reanudar hilo + acción nueva).
4. "olvídate de eso" aislado (cierre explícito sin nueva solicitud).
5. Cambio brusco de tema ("olvídate de lo anterior y crea la clase X").
6. Recomendación de relación -> aceptación explícita.
7. Fallo parcial previo -> "sí" -> retoma el residual.
8. Validación semántica: relación entre clases inexistentes.
9. Validación semántica: herencia cíclica.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest

from app.modules.assistant.application.services.dialog.dialog_manager import (
    DialogManager,
    DialogTurnResult,
)
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
    ContinuationOutcome,
    ContinuationPurpose,
    ContinuationState,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus
from tests.modules.assistant.test_dialog_conversations import (
    InMemoryContinuationRepository,
    InMemoryConversationReader,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_golden_1_dry_herencia_response_asks_direction():
    """Caso 1: Tras preguntar por el tipo de relación entre A y B, el usuario
    responde escuetamente 'herencia'. El sistema debe interpretar el slot
    tipo=GENERALIZATION y preguntar por la dirección (superclase/subclase)."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    # Turno 1: el usuario pide relacionar A con B sin especificar tipo
    t1 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona la clase Vehiculo con la clase Auto",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t1.status == "awaiting_input"
    assert "tipo de relación" in t1.assistant_message.lower()

    # Turno 2: respuesta seca 'herencia'
    t2 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="herencia",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t2.status == "awaiting_input"
    # Debe solicitar cuál es la clase padre / superclase
    msg = t2.assistant_message.lower()
    assert "padre" in msg or "superclase" in msg or "hereda" in msg


@pytest.mark.anyio
async def test_golden_2_continue_does_not_bypass_missing_fields():
    """Caso 2: 'continúa' o 'sí' no debe brincarse la validación de campos obligatorios."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    # Inicia relación sin tipo
    await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona Cliente con Factura",
            status=AgentMessageStatus.RUNNING,
        )
    )

    # Usuario dice solo "continúa"
    t2 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="continúa",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t2.status == "awaiting_input"
    assert t2.continuation is not None
    assert t2.continuation.state == ContinuationState.AWAITING_INPUT


@pytest.mark.anyio
async def test_golden_3_compound_continue_and_create_class():
    """Caso 3: Mensaje compuesto 'sí, continúa y además crea una clase llamada Árbol'.
    Debe respetar la continuación pendiente y además capturar la creación de la clase."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    # Inicia con una clase incompleta o relación con recomendación
    t1 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona Producto con Categoria",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t1.status == "awaiting_input"

    # Usuario pide recomendación
    t2 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="¿Qué relación me recomiendas?",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t2.status == "awaiting_input"
    assert "Opción A" in t2.assistant_message

    # Mensaje compuesto aceptando propuesta + nueva orden
    t3 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Sí, continúa y además crea una clase llamada Árbol",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t3.status == "ready_to_execute"
    assert "Producto" in t3.effective_request
    assert "Categoria" in t3.effective_request
    assert "crea una clase llamada Árbol" in t3.effective_request


@pytest.mark.anyio
async def test_golden_4_explicit_abandon_without_new_request():
    """Caso 4: 'olvídate de eso' o 'cancela eso' aislado cierra el hilo con close_reason='abandoned'
    o similar y responde amablemente sin intentar ejecutar nada."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    # Inicia hilo
    t1 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona Factura con Detalle",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t1.status == "awaiting_input"
    active_cont = repo.find_active_by_scope(project_id=project_id, user_id=user_id)
    assert active_cont is not None

    # Usuario cancela/abandona explícitamente sin nueva orden
    t2 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="olvídate de eso",
            status=AgentMessageStatus.RUNNING,
        )
    )
    # Debe ser declinado/cancelado de inmediato
    assert t2.status in ("declined", "pass_through")
    closed = repo.find_by_id(active_cont.id)
    assert closed.state in (ContinuationState.DECLINED, ContinuationState.EXPIRED)
    # Sin hilos activos restantes
    assert repo.find_active_by_scope(project_id=project_id, user_id=user_id) is None


@pytest.mark.anyio
async def test_golden_5_abrupt_topic_change_closes_old_thread():
    """Caso 5: Cambio brusco de tema cierra el hilo viejo y atiende la nueva solicitud."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    t1 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona Pedido con Entrega",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t1.status == "awaiting_input"
    old_cont = repo.find_active_by_scope(project_id=project_id, user_id=user_id)

    # Cambio explícito de tema
    t2 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Olvídate de lo anterior y crea una clase llamada Auditoría",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert t2.status == "pass_through"
    assert "crea una clase llamada Auditoría" in t2.effective_request
    closed = repo.find_by_id(old_cont.id)
    assert closed.state in (ContinuationState.DECLINED, ContinuationState.EXPIRED)
    assert closed.close_reason == ContinuationCloseReason.TOPIC_CHANGE


@pytest.mark.anyio
async def test_golden_6_recommendation_and_acceptance_cycle():
    """Caso 6: Ciclo de consulta de recomendación y posterior aceptación."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    dm = DialogManager(continuation_repository=repo)

    await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="Relaciona Factura con Cliente",
            status=AgentMessageStatus.RUNNING,
        )
    )
    rec = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="¿Qué relación me recomiendas entre Factura y Cliente?",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert rec.status == "awaiting_input"
    assert "Opción A" in rec.assistant_message

    acc = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="dale, aplica la opción A",
            status=AgentMessageStatus.RUNNING,
        )
    )
    assert acc.status == "ready_to_execute"
    assert "Factura" in acc.effective_request
    assert "Cliente" in acc.effective_request


@pytest.mark.anyio
async def test_golden_7_residual_retry_after_partial_failure():
    """Caso 7: Si un mensaje previo terminó con fallo parcial y hay una continuación
    RESIDUAL_RETRY activa, un 'sí', 'dale' o 'continúa' debe reanudar las tareas pendientes."""
    repo = InMemoryContinuationRepository()
    project_id = uuid4()
    user_id = "u1"
    root_id = uuid4()
    source_plan_id = uuid4()

    # Simulamos una continuación de reintento residual pendiente
    residual = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        root_message_id=root_id,
        source_plan_message_id=source_plan_id,
        effective_request="Crear atributo total en Factura",
        outcome=ContinuationOutcome.PARTIAL,
        purpose=ContinuationPurpose.RESIDUAL_RETRY,
        missing_fields=(),
    )
    repo.save(residual)

    dm = DialogManager(continuation_repository=repo)
    # El usuario responde afirmativamente "sí, reintenta"
    t1 = await dm.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            prompt="sí, reintenta",
            status=AgentMessageStatus.RUNNING,
        )
    )
    # Debe ser detectado como reintento o pass_through con intent RETRY
    assert t1.intent == "RETRY" or t1.status in ("ready_to_execute", "pass_through")


@pytest.mark.anyio
async def test_golden_8_semantic_validation_duplicate_relation():
    """Caso 8: Validación semántica: no intentar crear relaciones duplicadas idénticas."""
    from app.modules.assistant.domain.dialog.semantic_validators import validate_relation_semantics
    # Mock de elementos existentes
    existing_relations = [
        {"source": "Factura", "target": "Cliente", "type": "ASSOCIATION"}
    ]
    is_valid, error_msg = validate_relation_semantics(
        source="Factura",
        target="Cliente",
        rel_type="ASSOCIATION",
        existing_relations=existing_relations,
    )
    assert not is_valid
    assert "ya existe una relación" in error_msg.lower()


@pytest.mark.anyio
async def test_golden_9_semantic_validation_inheritance_cycle():
    """Caso 9: Validación semántica: prevención de herencia cíclica (A hereda de B y B de A)."""
    from app.modules.assistant.domain.dialog.semantic_validators import validate_inheritance_cycle
    # Si B ya hereda de A:
    existing_inheritance = [
        {"subclass": "B", "superclass": "A"}
    ]
    # No se puede hacer que A herede de B
    is_valid, error_msg = validate_inheritance_cycle(
        subclass="A",
        superclass="B",
        existing_inheritance=existing_inheritance,
    )
    assert not is_valid
    assert "cíclica" in error_msg.lower() or "ciclo" in error_msg.lower()
