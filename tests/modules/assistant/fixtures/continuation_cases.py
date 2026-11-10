"""Fixtures deterministas para casos de continuidad conversacional del asistente."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

# Límites de contexto y rendimiento fijados por la especificación y el plan
MAX_ACTIVE_FACTS: int = 20
MAX_ACTIVE_QUESTIONS: int = 20
MAX_RECENT_MESSAGES: int = 10
CONTINUATION_TTL_HOURS: int = 24
MAX_CANDIDATE_CONTINUATIONS: int = 3
MAX_EFFECTIVE_REQUEST_CHARS: int = 10_000


@dataclass(frozen=True, slots=True)
class ClarificationStep:
    prompt: str
    resolved_facts: list[dict[str, Any]]
    remaining_missing_keys: list[str]
    is_ready: bool


@dataclass(frozen=True, slots=True)
class ClarificationCase:
    case_id: str
    description: str
    initial_request: str
    initial_missing_fields: list[dict[str, Any]]
    steps: list[ClarificationStep]


@dataclass(frozen=True, slots=True)
class DecisionCase:
    prompt: str
    expected_decision: str  # "follow_up" | "new_request" | "decline" | "ambiguous"
    description: str


# Casos de prueba deterministas para la resolución de intenciones y continuidad
CLARIFICATION_CASES: list[ClarificationCase] = [
    ClarificationCase(
        case_id="relation-missing-type-and-cardinality",
        description="Petición de relación sin tipo ni cardinalidad, resuelta en dos pasos",
        initial_request="Relaciona Producto con Categoría",
        initial_missing_fields=[
            {
                "key": "relation.type",
                "action": "CREATE_RELATION",
                "critical": True,
                "question": "¿Qué tipo de relación deseas entre Producto y Categoría (asociación, composición, etc.)?",
            },
            {
                "key": "relation.endpoint_cardinalities",
                "action": "CREATE_RELATION",
                "critical": True,
                "question": "¿Cuáles son las cardinalidades en cada extremo?",
            },
        ],
        steps=[
            ClarificationStep(
                prompt="uno a muchos",
                resolved_facts=[
                    {"key": "relation.type", "value": "ASSOCIATION", "provenance": "followup-1"},
                    {"key": "relation.family", "value": "association", "provenance": "followup-1"},
                ],
                remaining_missing_keys=["relation.endpoint_cardinalities"],
                is_ready=False,
            ),
            ClarificationStep(
                prompt="1 en Categoría y 0..* en Producto",
                resolved_facts=[
                    {
                        "key": "relation.endpoint_cardinalities",
                        "value": {"Categoria": "1", "Producto": "0..*"},
                        "provenance": "followup-2",
                    }
                ],
                remaining_missing_keys=[],
                is_ready=True,
            ),
        ],
    ),
    ClarificationCase(
        case_id="attribute-missing-class",
        description="Creación de atributo sin clase especificada con resolución puntual",
        initial_request="Crea un atributo llamado precio",
        initial_missing_fields=[
            {
                "key": "attribute.target_class",
                "action": "CREATE_ATTRIBUTE",
                "critical": True,
                "question": "¿En qué clase deseas agregar el atributo `precio`?",
            }
        ],
        steps=[
            ClarificationStep(
                prompt="en la clase Producto",
                resolved_facts=[
                    {"key": "attribute.target_class", "value": "Producto", "provenance": "followup-1"}
                ],
                remaining_missing_keys=[],
                is_ready=True,
            )
        ],
    ),
    ClarificationCase(
        case_id="structural-missing-direction",
        description="Composición sin roles claros de todo/parte",
        initial_request="Crea una composición entre Casa y Habitación",
        initial_missing_fields=[
            {
                "key": "relation.direction",
                "action": "CREATE_RELATION",
                "critical": True,
                "question": "¿Cuál es la clase contenedora (el todo) y cuál la contenida (la parte)?",
            }
        ],
        steps=[
            ClarificationStep(
                prompt="Casa contiene a Habitación",
                resolved_facts=[
                    {"key": "relation.whole", "value": "Casa", "provenance": "followup-1"},
                    {"key": "relation.part", "value": "Habitación", "provenance": "followup-1"},
                ],
                remaining_missing_keys=[],
                is_ready=True,
            )
        ],
    ),
]

DECLINE_CASES: list[DecisionCase] = [
    DecisionCase("no", "decline", "Negación simple"),
    DecisionCase("cancela", "decline", "Instrucción de cancelar"),
    DecisionCase("olvídalo", "decline", "Descarte conversacional"),
    DecisionCase("déjalo así", "decline", "Cierre coloquial"),
    DecisionCase("ya no quiero", "decline", "Desistimiento explícito"),
    DecisionCase("no hagas nada", "decline", "Instrucción explícita de no actuar"),
]

NEW_REQUEST_CASES: list[DecisionCase] = [
    DecisionCase("Crea una clase llamada Cliente", "new_request", "Creación de clase no relacionada"),
    DecisionCase("Muéstrame el resumen del proyecto", "new_request", "Consulta general del proyecto"),
    DecisionCase("Elimina la clase Factura", "new_request", "Mutación distinta sobre otra entidad"),
    DecisionCase("Genera el diagrama ERD", "new_request", "Solicitud general de exportación o análisis"),
]

AMBIGUOUS_CASES: list[DecisionCase] = [
    DecisionCase("sí", "ambiguous", "Afirmación sin especificar cuál de varios pendientes"),
    DecisionCase("agrega eso", "ambiguous", "Puntero anafórico ambiguo ante múltiples candidatos"),
    DecisionCase("continúa", "ambiguous", "Orden de continuar cuando hay más de una continuación abierta"),
    DecisionCase("correcto", "ambiguous", "Aprobación genérica ambigua"),
]

CONTEXT_BOUNDS_FIXTURES: dict[str, Any] = {
    "max_active_facts": MAX_ACTIVE_FACTS,
    "max_active_questions": MAX_ACTIVE_QUESTIONS,
    "max_recent_messages": MAX_RECENT_MESSAGES,
    "ttl_hours": CONTINUATION_TTL_HOURS,
    "max_candidates": MAX_CANDIDATE_CONTINUATIONS,
    "max_request_chars": MAX_EFFECTIVE_REQUEST_CHARS,
}
