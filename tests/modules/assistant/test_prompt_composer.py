"""Pruebas para el compositor modular de prompts (PromptComposer)."""

import pytest

from app.modules.assistant.application.services.prompting.prompt_catalog import (
    create_default_prompt_catalog,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptCompositionContext,
)


def test_composer_always_includes_core_universal_and_phase_in_modular_mode():
    catalog = create_default_prompt_catalog()
    composer = PromptComposer(catalog=catalog, variant="modular")

    ctx = PromptCompositionContext(phase="execution")
    bundle = composer.compose(ctx)

    assert "core_universal" in bundle.policy_ids
    assert "phase_execution" in bundle.policy_ids
    assert bundle.system_text
    assert "Español" in bundle.system_text or "español" in bundle.system_text.lower()


def test_composer_is_deterministic_and_same_context_produces_identical_bundle():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
    )

    bundle1 = composer.compose(ctx)
    bundle2 = composer.compose(ctx)

    assert bundle1.policy_ids == bundle2.policy_ids
    assert bundle1.system_text == bundle2.system_text
    assert bundle1.estimated_tokens == bundle2.estimated_tokens


def test_composer_includes_attribute_rules_when_attribute_actions_authorized():
    composer = PromptComposer(variant="modular")
    ctx_without = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
    )
    bundle_without = composer.compose(ctx_without)

    ctx_with = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS", "CREATE_ATTRIBUTE"}),
    )
    bundle_with = composer.compose(ctx_with)

    assert "module_attributes" not in bundle_without.policy_ids
    assert "module_attributes" in bundle_with.policy_ids
    assert "CREATE_ATTRIBUTE" in bundle_with.system_text


def test_composer_includes_relation_rules_when_relation_actions_authorized():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION"}),
    )
    bundle = composer.compose(ctx)

    assert "module_relations" in bundle.policy_ids
    assert "CREATE_RELATION" in bundle.system_text
    assert "ASSOCIATION" in bundle.system_text


def test_composer_includes_deletion_rules_when_delete_action_authorized():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"DELETE_CLASS"}),
    )
    bundle = composer.compose(ctx)

    assert "module_deletion" in bundle.policy_ids
    assert "eliminación" in bundle.system_text.lower() or "borrado" in bundle.system_text.lower()


def test_composer_in_legacy_mode_returns_exact_legacy_prompt():
    composer = PromptComposer(variant="legacy")

    ctx_exec = PromptCompositionContext(phase="execution")
    bundle_exec = composer.compose(ctx_exec)
    from app.modules.assistant.application.services.prompting.legacy_prompts import (
        PLANNER_PROMPT,
        TOOL_PROMPT,
    )

    assert bundle_exec.system_text == TOOL_PROMPT
    assert bundle_exec.policy_ids == ("legacy_tool_prompt",)

    ctx_plan = PromptCompositionContext(phase="planning")
    bundle_plan = composer.compose(ctx_plan)
    assert bundle_plan.system_text == PLANNER_PROMPT
    assert bundle_plan.policy_ids == ("legacy_planner_prompt",)


def test_composer_does_not_expand_permissions():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_CLASS"}),
    )
    bundle = composer.compose(ctx)

    # Las reglas de eliminación y relaciones no deben estar presentes si no se autorizaron
    assert "module_deletion" not in bundle.policy_ids
    assert "module_relations" not in bundle.policy_ids
