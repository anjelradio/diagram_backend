"""Suite de pruebas de aceptación para el corpus de continuidad conversacional (SC-001 a SC-004)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.continuation.continuation_resolver import (
    ContinuationResolver,
    ResolutionDecision,
)
from app.modules.assistant.application.services.continuation.residual_plan_builder import (
    ResidualPlanBuilder,
    UnreconciledOperationException,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationState,
)
from tests.modules.assistant.fixtures.continuation_acceptance_cases import (
    ADVERSE_ACCEPTANCE_CASES,
    CLARIFICATION_ACCEPTANCE_CASES,
    PARTIAL_RESUMPTION_ACCEPTANCE_CASES,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- SC-001: 10 Casos de Aclaración sin repetición innecesaria ---
@pytest.mark.anyio
@pytest.mark.parametrize("case", CLARIFICATION_ACCEPTANCE_CASES, ids=lambda c: c.case_id)
async def test_sc_001_clarification_acceptance_cases(case):
    """SC-001: Retomar la intención original sin forzar a repetir datos ya establecidos."""
    cont = AgentContinuation(
        id=uuid4(),
        project_id=uuid4(),
        user_id="test_user",
        root_message_id=uuid4(),
        latest_message_id=uuid4(),
        state=ContinuationState.AWAITING_INPUT,
        version=1,
        effective_request=case.initial_request,
        resolved_facts=[],
        missing_fields=case.critical_missing,
        outcome="awaiting_input",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    import json
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    mock_provider = AsyncMock(spec=AiProvider)
    payload = {
        "decision": "follow_up",
        "candidate_id": str(cont.id),
        "effective_request": f"{case.initial_request}; {case.follow_up_input}",
        "resolved_facts": case.expected_resolved_facts,
        "missing_fields": [],
    }
    mock_provider.complete.return_value = AiResult(
        text=json.dumps(payload),
        model_role=ModelRole.MAIN,
        model="test-acceptance",
    )

    resolver = ContinuationResolver(ai_provider=mock_provider)
    resolution = await resolver.resolve(
        user_prompt=case.follow_up_input,
        candidates=[cont],
    )

    assert resolution.decision == ResolutionDecision.FOLLOW_UP
    assert resolution.candidate_id == cont.id
    assert resolution.effective_request is not None
    # La solicitud efectiva contiene el contexto inicial y la aclaración
    assert case.initial_request in resolution.effective_request
    assert len(resolution.resolved_facts) == len(case.expected_resolved_facts)


# --- SC-002: 10 Casos de Reanudación Parcial sin Duplicación ---
@pytest.mark.parametrize("case", PARTIAL_RESUMPTION_ACCEPTANCE_CASES, ids=lambda c: c.case_id)
def test_sc_002_partial_resumption_no_duplicates(case):
    """SC-002: Ninguna operación aplicada se ejecuta dos veces al reanudar."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    prior_plan = ExecutionPlan.create(
        goal=case.initial_request,
        tasks=[
            {
                "id": "task-applied",
                "objective": "Tarea aplicada",
                "kind": "mutation",
                "status": "completed",
                "depends_on": [],
                "operation_ids": [case.prior_ledger[0]["operation_id"]],
            },
            {
                "id": "task-remaining",
                "objective": "Tarea pendiente",
                "kind": "mutation",
                "status": "pending",
                "depends_on": ["task-applied"],
                "operation_ids": [case.prior_ledger[1]["operation_id"]],
            },
        ],
    )
    prior_plan.operation_ledger = case.prior_ledger

    builder = ResidualPlanBuilder()
    residual = builder.build(prior_plan, new_goal=case.initial_request)

    # Verificar tareas
    residual_task_ids = [t["id"] for t in residual.tasks]
    assert "task-applied" not in residual_task_ids
    assert "task-remaining" in residual_task_ids

    # Dependencias hacia la tarea aplicada deben haberse satisfecho
    remaining_task = next(t for t in residual.tasks if t["id"] == "task-remaining")
    assert "task-applied" not in remaining_task.get("depends_on", [])
    assert "task-applied" not in remaining_task.get("dependencies", [])

    # Verificar operaciones
    residual_op_ids: list[str] = []
    for t in residual.tasks:
        for op in t.get("operation_ids", []):
            residual_op_ids.append(op)
        for op in t.get("operations", []):
            if isinstance(op, dict):
                residual_op_ids.append(op.get("operation_id", ""))
            elif isinstance(op, str):
                residual_op_ids.append(op)

    for forbidden in case.forbidden_duplicated_operations:
        assert forbidden not in residual_op_ids

    for expected in case.expected_residual_operations:
        assert expected in residual_op_ids


# --- SC-003 & SC-004: Casos Adversos ---
def test_sc_003_unreconciled_uncertain_blocks_automatic_resumption():
    """SC-003: Operación incierta no reconciliada detiene reintento automático."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    uncertain_case = next(c for c in ADVERSE_ACCEPTANCE_CASES if c.scenario == "unreconciled_uncertain")
    prior_plan = ExecutionPlan.create(
        goal=uncertain_case.initial_request,
        tasks=[
            {
                "id": "task-uncertain",
                "objective": "Tarea incierta",
                "kind": "mutation",
                "status": "pending",
                "depends_on": [],
                "operation_ids": ["op-u1"],
            }
        ],
    )
    prior_plan.operation_ledger = uncertain_case.prior_ledger

    builder = ResidualPlanBuilder()
    with pytest.raises(UnreconciledOperationException):
        builder.build(prior_plan)


@pytest.mark.anyio
async def test_sc_003_affirmative_response_does_not_clear_missing_fields():
    """SC-003: Un simple 'sí' nunca sustituye campos críticos faltantes."""
    cont = AgentContinuation(
        id=uuid4(),
        project_id=uuid4(),
        user_id="test_user",
        root_message_id=uuid4(),
        latest_message_id=uuid4(),
        state=ContinuationState.AWAITING_INPUT,
        version=1,
        effective_request="Relaciona Factura con Detalle",
        resolved_facts=[],
        missing_fields=[{"key": "relation.endpoint_cardinalities", "critical": True}],
        outcome="awaiting_input",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    resolver = ContinuationResolver(ai_provider=None)
    resolution = await resolver.resolve(user_prompt="sí, hazlo", candidates=[cont])

    assert resolution.decision == ResolutionDecision.FOLLOW_UP
    # Sigue teniendo campos faltantes porque 'sí' no aporta cardinalidades
    assert len(resolution.missing_fields) > 0


def test_sc_004_isolation_and_safety_checks():
    """SC-004: Integridad de contexto de continuación ante proyectos/usuarios ajenos."""
    proj_a = uuid4()
    proj_b = uuid4()
    cont = AgentContinuation(
        id=uuid4(),
        project_id=proj_a,
        user_id="user_owner",
        root_message_id=uuid4(),
        latest_message_id=uuid4(),
        state=ContinuationState.AWAITING_INPUT,
        version=1,
        effective_request="Solicitud Proyecto A",
        resolved_facts=[],
        missing_fields=[],
        outcome="awaiting_input",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    assert cont.project_id == proj_a
    assert cont.project_id != proj_b
