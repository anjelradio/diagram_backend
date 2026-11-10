"""Pruebas para el flujo modular de continuidad conversacional y resolución reciente."""

import pytest

from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptCompositionContext,
)


def test_continuation_phase_includes_decision_contract_and_universal_core():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(phase="continuation")
    bundle = composer.compose(ctx)

    assert "core_universal" in bundle.policy_ids
    assert "phase_continuation" in bundle.policy_ids
    text = bundle.system_text.lower()
    assert "follow_up" in text
    assert "new_request" in text
    assert "decline" in text
    assert "ambiguous" in text


def test_continuation_rules_mandate_that_si_does_not_supply_name_or_cardinality():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(phase="continuation")
    bundle = composer.compose(ctx)

    text = bundle.system_text
    assert "«Sí» o confirmaciones genéricas solo aceptan propuestas concretas" in text
    assert "nunca son el valor de un nombre ni de una cardinalidad" in text


def test_continuation_rules_forbid_inventing_ids_or_entities():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(phase="continuation")
    bundle = composer.compose(ctx)

    text = bundle.system_text
    assert "NUNCA inventes IDs, UUIDs, clases, atributos ni relaciones" in text


def test_execution_phase_with_continuation_has_residual_awareness():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
        has_continuation=True,
    )
    bundle = composer.compose(ctx)

    assert "phase_execution" in bundle.policy_ids
    assert bundle.system_text
