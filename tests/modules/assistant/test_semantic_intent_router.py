import json
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiRequest,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.intent.semantic_intent_router import (
    SemanticCategory,
    SemanticIntentRouter,
)


class MockAiProvider(AiProvider):
    def __init__(self, response_json: dict) -> None:
        self.response_json = response_json
        self.last_request: AiRequest | None = None

    async def complete(self, request: AiRequest) -> AiResult:
        self.last_request = request
        return AiResult(
            text=json.dumps(self.response_json),
            model_role=ModelRole.MAIN,
            model="mock-qwen",
            completed=True,
        )


@pytest.mark.anyio
async def test_semantic_intent_router_direct_action():
    provider = MockAiProvider({
        "category": "DIRECT_ACTION",
        "reasoning": "El usuario solicita explícitamente crear una clase.",
        "resolved_goal": "Crear la clase Factura con los atributos numero y fecha.",
        "requires_mutation": True,
        "missing_info": None,
        "clarification_question": None,
    })
    router = SemanticIntentRouter(ai_provider=provider)
    decision = await router.route(user_message="Crea la clase Factura con numero y fecha")

    assert decision.category == SemanticCategory.DIRECT_ACTION
    assert decision.requires_mutation is True
    assert "Factura" in decision.resolved_goal
    assert decision.clarification_question is None


@pytest.mark.anyio
async def test_semantic_intent_router_continuation_decontextualization():
    provider = MockAiProvider({
        "category": "CONTINUATION_OR_ANAPHORA",
        "reasoning": "El usuario se refiere a la generalización recomendada en el turno anterior.",
        "resolved_goal": "Crear una relación de herencia (generalización) donde Usuario es la superclase y Administrador es la subclase.",
        "requires_mutation": True,
        "missing_info": None,
        "clarification_question": None,
    })
    router = SemanticIntentRouter(ai_provider=provider)
    recent_turns = [
        {
            "user": "¿En UML qué relación es la más adecuada si un Administrador es un tipo de Usuario?",
            "assistant": "La relación más adecuada es Generalización donde Usuario es la superclase y Administrador la subclase.",
        }
    ]
    decision = await router.route(
        user_message="Aplica esa generalización en las clases",
        recent_turns=recent_turns,
        existing_classes=["Usuario", "Administrador"],
    )

    assert decision.category == SemanticCategory.CONTINUATION_OR_ANAPHORA
    assert decision.requires_mutation is True
    assert "Usuario" in decision.resolved_goal
    assert "Administrador" in decision.resolved_goal
    assert "generalización" in decision.resolved_goal


@pytest.mark.anyio
async def test_semantic_intent_router_compound_action():
    provider = MockAiProvider({
        "category": "COMPOUND_ACTION",
        "reasoning": "El usuario acepta la relación anterior y además pide una nueva clase Proveedor.",
        "resolved_goal": "1. Crear relación de generalización entre Usuario y Administrador. 2. Crear clase Proveedor con nombre y telefono.",
        "requires_mutation": True,
        "missing_info": None,
        "clarification_question": None,
    })
    router = SemanticIntentRouter(ai_provider=provider)
    decision = await router.route(
        user_message="Aplica esa generalización y además crea una clase Proveedor con nombre y telefono",
        recent_turns=[{"user": "...", "assistant": "..."}],
    )

    assert decision.category == SemanticCategory.COMPOUND_ACTION
    assert decision.requires_mutation is True
    assert "Proveedor" in decision.resolved_goal


@pytest.mark.anyio
async def test_semantic_intent_router_needs_more_context():
    provider = MockAiProvider({
        "category": "NEEDS_MORE_CONTEXT",
        "reasoning": "El usuario dice 'relaciona las clases' pero hay 4 clases en el lienzo y no indica cuáles.",
        "resolved_goal": "",
        "requires_mutation": False,
        "missing_info": ["clases_a_relacionar", "tipo_relacion"],
        "clarification_question": "Tienes las clases Usuario, Pedido, Producto y Factura en tu diagrama. ¿Entre cuáles te gustaría crear la relación y de qué tipo?",
    })
    router = SemanticIntentRouter(ai_provider=provider)
    decision = await router.route(
        user_message="Relaciona las clases",
        existing_classes=["Usuario", "Pedido", "Producto", "Factura"],
    )

    assert decision.category == SemanticCategory.NEEDS_MORE_CONTEXT
    assert decision.requires_mutation is False
    assert decision.clarification_question is not None
    assert "Usuario, Pedido, Producto y Factura" in decision.clarification_question


@pytest.mark.anyio
async def test_semantic_intent_router_conceptual_consultation():
    provider = MockAiProvider({
        "category": "CONCEPTUAL_CONSULTATION",
        "reasoning": "Pregunta teórica de modelado UML sin intención de modificar el diagrama.",
        "resolved_goal": "¿Cuál es la diferencia entre composición y agregación en UML?",
        "requires_mutation": False,
        "missing_info": None,
        "clarification_question": None,
    })
    router = SemanticIntentRouter(ai_provider=provider)
    decision = await router.route(
        user_message="¿Qué diferencia hay entre composición y agregación?",
    )

    assert decision.category == SemanticCategory.CONCEPTUAL_CONSULTATION
    assert decision.requires_mutation is False


@pytest.mark.anyio
async def test_semantic_intent_router_fallback_without_ai():
    router = SemanticIntentRouter(ai_provider=None)

    # Cancelación
    d_cancel = await router.route(user_message="Cancela eso")
    assert d_cancel.category == SemanticCategory.DECLINE_OR_CANCEL

    # Pregunta conceptual
    d_q = await router.route(user_message="¿Qué es una asociación?")
    assert d_q.category == SemanticCategory.CONCEPTUAL_CONSULTATION

    # Acción directa
    d_act = await router.route(user_message="Crea la clase Vehiculo")
    assert d_act.category == SemanticCategory.DIRECT_ACTION
    assert d_act.requires_mutation is True
