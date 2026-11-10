"""Pruebas de regresión para flujos simples comparando variantes legacy y modular."""

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiContentPart,
    AiRequest,
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.services.prompting.prompt_catalog import (
    create_default_prompt_catalog,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptCompositionContext,
)


def test_modular_reduces_instruction_volume_by_at_least_30_percent_for_simple_tasks():
    composer_legacy = PromptComposer(variant="legacy")
    composer_modular = PromptComposer(variant="modular")

    ctx_simple = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
    )

    bundle_legacy = composer_legacy.compose(ctx_simple)
    bundle_modular = composer_modular.compose(ctx_simple)

    legacy_len = len(bundle_legacy.system_text)
    modular_len = len(bundle_modular.system_text)

    reduction = (legacy_len - modular_len) / legacy_len
    # El criterio SC-003 exige al menos 30% de reducción de instrucciones en solicitudes simples
    assert reduction >= 0.30, f"Reducción obtenida: {reduction:.2%}, esperada >= 30%"
    assert bundle_modular.estimated_tokens < bundle_legacy.estimated_tokens


def test_simple_class_creation_prompts_retain_essential_safety_rules():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
    )
    bundle = composer.compose(ctx)

    # Reglas esenciales presentes
    text = bundle.system_text.lower()
    assert "herramientas" in text
    assert "datos" in text  # aislamiento de datos vs instrucciones
    assert "uuid" in text or "id" in text
    assert "afirmar" in text or "confirmad" in text  # solo afirmar cambios confirmados


def test_query_flow_does_not_contain_mutation_instructions():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset(),  # solo consulta
        derived_capabilities=frozenset({"query"}),
    )
    bundle = composer.compose(ctx)

    assert "module_relations" not in bundle.policy_ids
    assert "module_deletion" not in bundle.policy_ids
    assert "module_attributes" not in bundle.policy_ids
