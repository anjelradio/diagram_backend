"""Pruebas integrales para los escenarios conversacionales del asistente:
1. Mutación directa y aislamiento/ignorado de llaves PK y FK (Caso de Uso 1).
2. Consultas de orientación, sugerencias de diseño y UML 2.5 abierto (Caso de Uso 2).
3. Diálogo contextual, continuaciones y consolidación multi-turno (Caso de Uso 3).
4. Casos compuestos 'Dos en Uno' (mutación + consulta).
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.intent import (
    MetamodelGateKind,
    SemanticCategory,
    SemanticIntentRouter,
    check_metamodel_gate,
)
from app.modules.assistant.application.services.dialog.turn_signals import (
    extract_class_hints_from_key_request,
    is_isolated_fk_request,
    is_isolated_pk_request,
)
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    requires_mutation,
    requires_plan,
)
from app.modules.assistant.domain.dialog.key_attribute_rules import (
    extract_referenced_entity_from_fk,
    filter_secondary_attributes,
    is_foreign_key_name,
    is_primary_key_name,
)
from app.modules.assistant.application.services.diagram.diagram_relation_tools import (
    _cardinality,
)
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality


# ============================================================================
# BLOQUE 1: Mutación Directa e Intercepción / Ignorado de Llaves (Caso de Uso 1)
# ============================================================================

def test_isolated_fk_intercepted_at_metamodel_gate():
    """Peticiones aisladas de FK (snake_case, camelCase o explícitas) se interceptan en 0 tokens."""
    prompts = [
        "Crea una llave foránea en la clase Producto",
        "Crea una clave foránea en Producto referenciando a Categoría",
        "Crea el atributo categoria_id en la clase Producto",
        "Agrega el campo categoriaId a Producto",
        "Añade el atributo id_categoria en la clase Producto",
        "Pon categoriaId en Producto",
        "Pon categoria_id en Producto",
    ]
    for prompt in prompts:
        decision = check_metamodel_gate(prompt, existing_classes=["Producto", "Categoria"])
        assert decision is not None, f"Falló para: {prompt}"
        assert decision.kind == MetamodelGateKind.ISOLATED_FK
        assert "no se agregan manualmente como atributos" in decision.explanation
        assert "generan automáticamente al crear la relación" in decision.explanation


def test_isolated_pk_intercepted_at_metamodel_gate():
    """Peticiones aisladas de PK se interceptan explicando que id: UUID ya existe."""
    prompts = [
        "Crea una llave primaria en Producto",
        "Crea una clave primaria en la clase Usuario",
        "Crea el atributo id en la clase Producto",
        "Agrega el campo id a Usuario",
        "Agrega id a Usuario",
        "Pon id en Usuario",
        "Añade el atributo pk en Factura",
    ]
    for prompt in prompts:
        decision = check_metamodel_gate(prompt, existing_classes=["Producto", "Usuario", "Factura"])
        assert decision is not None, f"Falló para: {prompt}"
        assert decision.kind == MetamodelGateKind.ISOLATED_PK
        assert "cuenta automáticamente con su propia llave primaria" in decision.explanation


def test_mixed_class_creation_does_not_trigger_metamodel_gate():
    """Cuando se crea una clase con atributos mixtos (ordinarios + id + categoria_id), no se bloquea."""
    prompt = "Crea la clase Producto con id, nombre, precio y categoria_id"
    decision = check_metamodel_gate(prompt, existing_classes=["Categoria"])
    assert decision is None

    # En la separación de atributos secundarios, id y categoria_id se ignoran limpiamente
    attributes = [
        {"name": "id", "data_type": "UUID"},
        {"name": "nombre", "data_type": "TEXT"},
        {"name": "precio", "data_type": "DECIMAL"},
        {"name": "categoria_id", "data_type": "INTEGER"},
        {"name": "categoriaId", "data_type": "INTEGER"},
    ]
    valid, ignored = filter_secondary_attributes(attributes, class_name="Producto")
    assert [a["name"] for a in valid] == ["nombre", "precio"]
    assert [a["name"] for a in ignored] == ["id", "categoria_id", "categoriaId"]


def test_cardinality_normalization_and_aliases():
    """Normaliza 1..1 a EXACTLY_ONE y maneja alias comunes sin lanzar excepciones."""
    assert _cardinality("1") == DiagramCardinality.EXACTLY_ONE
    assert _cardinality("1..1") == DiagramCardinality.EXACTLY_ONE
    assert _cardinality("0..1") == DiagramCardinality.ZERO_OR_ONE
    assert _cardinality("0..*") == DiagramCardinality.ZERO_OR_MORE
    assert _cardinality("1..*") == DiagramCardinality.ONE_OR_MORE
    assert _cardinality("many") == DiagramCardinality.ZERO_OR_MORE
    assert _cardinality(None) is None


# ============================================================================
# BLOQUE 2: Consultas de Orientación y Sugerencias (Caso de Uso 2)
# ============================================================================

@pytest.mark.anyio
async def test_attribute_suggestion_needs_class_when_diagram_empty():
    """Si el usuario pide sugerencias de atributos pero el diagrama está vacío, pide la entidad."""
    ai_provider = AsyncMock(spec=AiProvider)
    ai_provider.complete.return_value = AiResult(
        text='{"category":"NEEDS_MORE_CONTEXT","reasoning":"Falta clase objetivo","resolved_goal":"","requires_mutation":false,"missing_info":["target_class"],"clarification_question":"¿Para qué clase o entidad de tu sistema deseas que te sugiera atributos?"}',
        model_role=ModelRole.MAIN,
        model="mock",
        completed=True,
    )
    router = SemanticIntentRouter(ai_provider)
    decision = await router.route(
        user_message="¿Qué atributos me sugieres?",
        existing_classes=[],
    )
    assert decision.category == SemanticCategory.NEEDS_MORE_CONTEXT
    assert "target_class" in decision.missing_info
    assert "clase o entidad" in (decision.clarification_question or "").lower()


@pytest.mark.anyio
async def test_attribute_suggestion_infers_single_existing_class():
    """Si en el diagrama hay solo 1 clase, sugiere atributos para esa clase directamente."""
    ai_provider = AsyncMock(spec=AiProvider)
    ai_provider.complete.return_value = AiResult(
        text='{"category":"CONCEPTUAL_CONSULTATION","reasoning":"Se infiere la única clase Usuario","resolved_goal":"Sugerir atributos para la clase Usuario","requires_mutation":false,"missing_info":[],"clarification_question":null}',
        model_role=ModelRole.MAIN,
        model="mock",
        completed=True,
    )
    router = SemanticIntentRouter(ai_provider)
    decision = await router.route(
        user_message="¿Qué atributos me recomiendas?",
        existing_classes=["Usuario"],
    )
    assert decision.category == SemanticCategory.CONCEPTUAL_CONSULTATION
    assert decision.requires_mutation is False
    assert "Usuario" in decision.resolved_goal


def test_open_conceptual_uml_consultation_intent():
    """Preguntas abiertas teóricas de UML 2.5 son clasificadas como consulta sin mutación."""
    prompts = [
        "¿Cuál es la diferencia entre generalización y herencia?",
        "¿Qué significa la relación de asociación?",
        "¿Cuándo debería usar composición en lugar de agregación?",
        "¿Para qué sirve una clase puente en una relación de muchos a muchos?",
    ]
    for prompt in prompts:
        intent = classify_agent_intent(prompt)
        assert intent.action == "query"
        assert intent.requires_mutation is False
        assert requires_mutation(prompt) is False
        assert requires_plan(prompt) is False


# ============================================================================
# BLOQUE 3: Diálogo Contextual, Continuaciones y Recapitulación (Caso de Uso 3)
# ============================================================================

@pytest.mark.anyio
async def test_affirmative_followup_resolves_previous_suggestion():
    """Cuando el usuario dice 'sí, hazlo', descontextualiza la propuesta del turno anterior."""
    ai_provider = AsyncMock(spec=AiProvider)
    ai_provider.complete.return_value = AiResult(
        text='{"category":"CONTINUATION_OR_ANAPHORA","reasoning":"Usuario confirma la sugerencia de Administrador y Usuario","resolved_goal":"Crear la clase Administrador con atributos nivel_acceso y departamento, y crear la relación de generalización entre Administrador y Usuario donde Usuario es la superclase y Administrador es la subclase","requires_mutation":true,"missing_info":[],"clarification_question":null}',
        model_role=ModelRole.MAIN,
        model="mock",
        completed=True,
    )
    router = SemanticIntentRouter(ai_provider)
    recent_turns = [
        {
            "message_id": str(uuid4()),
            "user": "¿Qué atributos me recomiendas para Administrador y qué relación con Usuario?",
            "assistant": "Para Administrador recomiendo nivel_acceso y departamento. Para relacionarla con Usuario recomiendo Generalización (Usuario superclase, Administrador subclase). ¿Deseas que implemente estos cambios en tu lienzo?",
        }
    ]
    decision = await router.route(
        user_message="Sí, hazlo",
        recent_turns=recent_turns,
        existing_classes=["Usuario"],
    )
    assert decision.category == SemanticCategory.CONTINUATION_OR_ANAPHORA
    assert decision.requires_mutation is True
    assert "Administrador" in decision.resolved_goal
    assert "generalización" in decision.resolved_goal.lower()


@pytest.mark.anyio
async def test_multi_turn_global_consolidation():
    """Cuando el usuario dice 'implementa todo eso', consolida todas las entidades del hilo."""
    ai_provider = AsyncMock(spec=AiProvider)
    ai_provider.complete.return_value = AiResult(
        text='{"category":"CONTINUATION_OR_ANAPHORA","reasoning":"Consolida hilo incremental de Usuario, Rol y su relación","resolved_goal":"Crear la clase Usuario con atributos nombre y email; crear la clase Rol con atributos nombre y descripcion; y crear la relación de asociación de 1 a N entre Rol y Usuario","requires_mutation":true,"missing_info":[],"clarification_question":null}',
        model_role=ModelRole.MAIN,
        model="mock",
        completed=True,
    )
    router = SemanticIntentRouter(ai_provider)
    recent_turns = [
        {
            "message_id": str(uuid4()),
            "user": "¿Qué atributos sugieres para Usuario?",
            "assistant": "Recomiendo nombre y email para Usuario.",
        },
        {
            "message_id": str(uuid4()),
            "user": "¿Y qué atributos para Rol?",
            "assistant": "Recomiendo nombre y descripcion para Rol.",
        },
        {
            "message_id": str(uuid4()),
            "user": "¿Y cómo deberían relacionarse?",
            "assistant": "Una relación de asociación 1 a N donde 1 Rol tiene muchos Usuarios. ¿Deseas que implemente todo esto?",
        },
    ]
    decision = await router.route(
        user_message="Bien, implementa todo eso",
        recent_turns=recent_turns,
        existing_classes=[],
    )
    assert decision.category == SemanticCategory.CONTINUATION_OR_ANAPHORA
    assert decision.requires_mutation is True
    assert "Usuario" in decision.resolved_goal
    assert "Rol" in decision.resolved_goal
    assert "asociación" in decision.resolved_goal.lower()


# ============================================================================
# BLOQUE 4: Casos Compuestos 'Dos en Uno' (Mutación + Consulta)
# ============================================================================

def test_compound_mutation_and_query_requires_plan():
    """Solicitudes que combinan mutación y consulta activan plan y mutación."""
    prompt = "Crea la clase Factura con numero y total, y dime qué relación debería tener con Cliente"
    intent = classify_agent_intent(prompt)
    assert intent.requires_mutation is True
    assert requires_mutation(prompt) is True
    assert requires_plan(prompt) is True


@pytest.mark.anyio
async def test_cyclical_flow_from_mutation_to_consultation_to_continuation():
    """Verifica la convergencia cíclica Caso 1 (Mutación) -> Caso 2 (Consulta) -> Caso 3 (Continuación)."""
    # 1. Simular que en Turno 1 se creó Factura (Caso 1)
    turn_1 = {
        "message_id": str(uuid4()),
        "user": "Crea la clase Factura con numero y total",
        "assistant": "He creado la clase Factura con los atributos numero: TEXT y total: DECIMAL.",
        "confirmed_operations": [{"type": "create_class", "name": "Factura"}],
    }

    # 2. En Turno 2, el usuario consulta sugerencias para 'esa clase' (Caso 2)
    mock_provider_consult = AsyncMock()
    mock_provider_consult.complete.return_value = AiResult(
        text='{"category": "CONCEPTUAL_CONSULTATION", "reasoning": "Consulta orientativa sobre la clase recién creada Factura", "resolved_goal": "Sugerir atributos complementarios para Factura", "requires_mutation": false, "missing_info": [], "clarification_question": null}',
        model_role=ModelRole.MAIN,
        model="qwen-test",
    )
    router = SemanticIntentRouter(ai_provider=mock_provider_consult)
    decision_consult = await router.route(
        user_message="¿Qué otros atributos me recomiendas para esa clase?",
        recent_turns=[turn_1],
        existing_classes=["Factura"],
    )
    assert decision_consult.category == SemanticCategory.CONCEPTUAL_CONSULTATION
    assert decision_consult.requires_mutation is False

    # 3. Simular que el asistente respondió con la recomendación y la pregunta CTA
    turn_2 = {
        "message_id": str(uuid4()),
        "user": "¿Qué otros atributos me recomiendas para esa clase?",
        "assistant": "Te recomiendo agregar fecha_emision (DATE) y estado (TEXT). ¿Deseas que implemente estos cambios en tu lienzo?",
    }

    # 4. En Turno 3, el usuario responde afirmativamente (Caso 3 -> vuelve a Caso 1)
    mock_provider_confirm = AsyncMock()
    mock_provider_confirm.complete.return_value = AiResult(
        text='{"category": "CONTINUATION_OR_ANAPHORA", "reasoning": "Confirma agregar los atributos recomendados para Factura", "resolved_goal": "Agregar a Factura los atributos fecha_emision: DATE y estado: TEXT", "requires_mutation": true, "missing_info": [], "clarification_question": null}',
        model_role=ModelRole.MAIN,
        model="qwen-test",
    )
    router_confirm = SemanticIntentRouter(ai_provider=mock_provider_confirm)
    decision_confirm = await router_confirm.route(
        user_message="Sí, hazlo",
        recent_turns=[turn_1, turn_2],
        existing_classes=["Factura"],
    )
    assert decision_confirm.category == SemanticCategory.CONTINUATION_OR_ANAPHORA
    assert decision_confirm.requires_mutation is True
    assert "Factura" in decision_confirm.resolved_goal
    assert "fecha_emision" in decision_confirm.resolved_goal
