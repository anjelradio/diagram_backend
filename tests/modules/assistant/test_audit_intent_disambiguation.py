import pytest

from app.modules.assistant.application.services.intent.semantic_intent_router import (
    SemanticCategory,
    SemanticIntentRouter,
)
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    has_direct_mutation_command,
    is_audit_query,
    requires_mutation,
)
from app.modules.assistant.application.services.planning.action_planner import ActionPlanner


@pytest.mark.parametrize(
    "audit_prompt",
    [
        "¿Quién creó la clase Producto?",
        "quien creo la clase Producto",
        "¿Quién modificó la clase Producto?",
        "¿Quién eliminó el atributo stock de la clase Pedido?",
        "¿Quién borró la relación entre Cliente y Factura?",
        "¿Quién creó la relación entre Cliente y Factura?",
        "¿Qué hizo Juan hoy?",
        "que hizo juan hoy",
        "¿Qué cambios realizó María ayer?",
        "¿Qué hizo Carlos en estos últimos días?",
        "¿Qué hizo Juan el 2026-11-05?",
        "¿Qué cambios ha tenido la clase Usuario en la última semana?",
        "¿Qué modificaciones se han hecho hoy en el proyecto?",
        "¿Quiénes estuvieron trabajando en el diagrama esta semana?",
        "¿Quién añadió el atributo precio a Producto?",
        "¿Qué usuario modificó la clase Pedido?",
        "¿Cuál usuario eliminó la clase Factura?",
    ],
)
def test_audit_queries_are_immunized_from_mutation(audit_prompt: str):
    """Verifica el Nivel 1 de Blindaje: is_audit_query neutraliza toda mutación."""
    assert is_audit_query(audit_prompt) is True
    assert has_direct_mutation_command(audit_prompt) is False
    assert requires_mutation(audit_prompt) is False

    intent = classify_agent_intent(audit_prompt)
    assert intent.action == "query"
    assert intent.scope == "audit"
    assert intent.requires_mutation is False

    # El plan directo debe ser siempre de tipo 'answer'
    plan = ActionPlanner.build_direct_plan(audit_prompt)
    assert len(plan.tasks) == 1
    assert plan.tasks[0]["kind"] == "answer"


@pytest.mark.parametrize(
    "mutation_prompt",
    [
        "Crea la clase Producto",
        "crear clase Pedido con total y fecha",
        "Agrega el atributo stock a Pedido",
        "Elimina la relación entre Cliente y Factura",
        "Modifica el nombre de la clase Producto a Item",
        "Borra la clase Detalle",
        "Relaciona Cliente con Factura mediante composición",
    ],
)
def test_imperative_mutations_are_not_confused_with_audit(mutation_prompt: str):
    """Verifica que las órdenes imperativas sigan clasificándose como mutaciones."""
    assert is_audit_query(mutation_prompt) is False
    assert has_direct_mutation_command(mutation_prompt) is True
    assert requires_mutation(mutation_prompt) is True

    intent = classify_agent_intent(mutation_prompt)
    assert intent.requires_mutation is True
    assert intent.action in ("create", "update", "delete")


@pytest.mark.parametrize(
    "conceptual_prompt",
    [
        "¿Qué atributos me sugieres para la clase Producto?",
        "¿Qué atributos puedo colocar en la clase Usuario?",
        "¿Cómo debería relacionar Pedido con Cliente?",
        "¿Qué significa una relación de composición en UML?",
        "¿Qué me recomiendas para el modelo de ventas?",
    ],
)
def test_conceptual_consultations_are_not_confused_with_audit(conceptual_prompt: str):
    """Verifica que las consultas conceptuales y sugerencias no se confundan con auditoría."""
    assert is_audit_query(conceptual_prompt) is False
    assert requires_mutation(conceptual_prompt) is False

    intent = classify_agent_intent(conceptual_prompt)
    assert intent.action == "query"
    assert intent.scope != "audit"
    assert intent.requires_mutation is False


@pytest.mark.anyio
async def test_semantic_router_fallback_categorizes_audit_query():
    """Verifica que el enrutador semántico clasifique las consultas como AUDIT_QUERY."""
    router = SemanticIntentRouter(ai_provider=None)  # Usa fallback heurístico
    
    decision = await router.route(user_message="¿Quién creó la clase Producto?")
    assert decision.category == SemanticCategory.AUDIT_QUERY
    assert decision.requires_mutation is False

    decision2 = await router.route(user_message="¿Qué hizo Juan hoy?")
    assert decision2.category == SemanticCategory.AUDIT_QUERY
    assert decision2.requires_mutation is False

    decision3 = await router.route(user_message="¿Qué atributos me sugieres para la clase Producto?")
    assert decision3.category == SemanticCategory.CONCEPTUAL_CONSULTATION
    assert decision3.requires_mutation is False

    decision4 = await router.route(user_message="Crea la clase Producto")
    assert decision4.category == SemanticCategory.DIRECT_ACTION
    assert decision4.requires_mutation is True
