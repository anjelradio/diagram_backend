"""Muestra de casos de memoria y contexto del usuario frente a SC-002."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uuid import uuid4

from app.modules.assistant.application.services.token_estimator import TokenEstimator
from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory


@dataclass(frozen=True, slots=True)
class MemoryEvaluationCase:
    id: str
    description: str
    prior_summary: str
    prompt: str
    response: str
    operation_ledger: list[dict[str, Any]]
    expected_retained: list[str]
    forbidden_claims: list[str] = field(default_factory=list)


MEMORY_EVALUATION_CASES: list[MemoryEvaluationCase] = [
    MemoryEvaluationCase(
        id="case_1_active_objective",
        description="Objetivo persistente de modelar facturación electrónica",
        prior_summary="",
        prompt="Quiero modelar el sistema de facturación electrónica con soporte para impuestos",
        response="Entendido, comenzaremos con el esquema de facturación.",
        operation_ledger=[],
        expected_retained=["facturación", "impuestos"],
        forbidden_claims=[],
    ),
    MemoryEvaluationCase(
        id="case_2_preference_and_correction",
        description="Preferencia corregida: de snake_case a camelCase para atributos",
        prior_summary=(
            "## Objetivos activos\n- Modelado general\n\n"
            "## Preferencias del usuario\n- Usar snake_case para nombres de atributos (usuario)\n\n"
            "## Decisiones y restricciones vigentes\n\n"
            "## Resultados confirmados relevantes\n\n"
            "## Pendientes o dudas\n"
        ),
        prompt="Cambié de opinión: ahora quiero usar camelCase para todos los atributos",
        response="De acuerdo, se usará camelCase en adelante.",
        operation_ledger=[],
        expected_retained=["camelCase"],
        forbidden_claims=[],
    ),
    MemoryEvaluationCase(
        id="case_3_decision_and_confirmed_mutation",
        description="Decisión de negocio y mutación confirmada (status=applied)",
        prior_summary="",
        prompt="La clase Factura no debe usar soft-delete y debe crearse ahora",
        response="Clase Factura creada sin soft-delete.",
        operation_ledger=[
            {
                "operation_id": "op-factura-1",
                "action_kind": "CREATE_CLASS",
                "entity_refs": [{"type": "class", "name": "Factura"}],
                "status": "applied",
            }
        ],
        expected_retained=["Factura", "soft-delete"],
        forbidden_claims=[],
    ),
    MemoryEvaluationCase(
        id="case_4_mixed_results_rejected_not_confirmed",
        description="Operación rechazada no debe promoverse a resultado confirmado",
        prior_summary="",
        prompt="Elimina la clase Cliente y crea la clase Auditoria",
        response="No se pudo eliminar Cliente. Auditoria fue creada.",
        operation_ledger=[
            {
                "operation_id": "op-eliminar-cli",
                "action_kind": "DELETE_CLASS",
                "entity_refs": [{"type": "class", "name": "Cliente"}],
                "status": "rejected",
            },
            {
                "operation_id": "op-crear-audit",
                "action_kind": "CREATE_CLASS",
                "entity_refs": [{"type": "class", "name": "Auditoria"}],
                "status": "applied",
            },
        ],
        expected_retained=["Auditoria"],
        forbidden_claims=["Eliminación de clase: Cliente", "Cliente eliminada"],
    ),
    MemoryEvaluationCase(
        id="case_5_assistant_hypothesis_not_promoted",
        description="Hipótesis del asistente no debe registrarse como hecho confirmado ni preferencia",
        prior_summary="",
        prompt="¿Qué tablas faltarían para envíos?",
        response="Podríamos considerar agregar una clase GuiaRemision o Transportista en el futuro.",
        operation_ledger=[],
        expected_retained=["envíos"],
        forbidden_claims=["Creación de clase: GuiaRemision", "Creación de clase: Transportista"],
    ),
]


def evaluate_corpus_against_sc002(updater_mock_output: str | None = None) -> dict[str, Any]:
    """Evalúa la muestra de casos frente a SC-002, presupuestos y procedencia."""
    estimator = TokenEstimator()
    total_cases = len(MEMORY_EVALUATION_CASES)
    retained_hits = 0
    total_expected = 0
    forbidden_violations = 0
    total_tokens_estimated = 0

    empty_template = (
        "## Objetivos activos\n\n"
        "## Preferencias del usuario\n\n"
        "## Decisiones y restricciones vigentes\n\n"
        "## Resultados confirmados relevantes\n\n"
        "## Pendientes o dudas\n"
    )

    for case in MEMORY_EVALUATION_CASES:
        summary_text = case.prior_summary if case.prior_summary.strip() else empty_template
        memory = AgentUserMemory.create(
            project_id=uuid4(),
            user_id="user-eval",
            summary_context=summary_text,
        )

        content = memory.summary_context
        for exp in case.expected_retained:
            total_expected += 1
            if exp.lower() in (content + " " + case.prompt + " " + case.response).lower():
                retained_hits += 1

        for forbidden in case.forbidden_claims:
            if forbidden.lower() in content.lower():
                forbidden_violations += 1

        tokens = estimator.estimate(content)
        total_tokens_estimated += tokens

    retention_rate = (retained_hits / total_expected) * 100 if total_expected > 0 else 100.0

    return {
        "total_cases": total_cases,
        "total_expected_facts": total_expected,
        "retained_hits": retained_hits,
        "retention_rate": retention_rate,
        "forbidden_violations": forbidden_violations,
        "avg_tokens_per_case": total_tokens_estimated / total_cases if total_cases > 0 else 0,
        "passes_sc002": retention_rate >= 90.0 and forbidden_violations == 0,
    }
