"""Pruebas de flujos especializados: relaciones, cardinalidades, herencia y reglas encadenadas."""

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


def test_implicit_relation_in_prompt_includes_relation_module():
    composer = PromptComposer(variant="modular")
    # "Cat hereda de Animal" -> derived_capabilities={"relations"}
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION"}),
        derived_capabilities=frozenset({"relations"}),
    )
    bundle = composer.compose(ctx)

    assert "module_relations" in bundle.policy_ids
    assert "GENERALIZATION" in bundle.system_text
    assert "cabeza" in bundle.system_text.lower()


def test_relation_rules_include_cardinalities_and_structural_invariants():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION"}),
    )
    bundle = composer.compose(ctx)

    text = bundle.system_text
    assert "ASSOCIATION" in text
    assert "source_cardinality" in text
    assert "target_cardinality" in text
    assert "COMPOSITION" in text
    assert "AGGREGATION" in text
    assert "diamante" in text


def test_intermediate_class_and_fk_rules_preserved_in_execution_phase():
    composer = PromptComposer(variant="modular")
    ctx = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION"}),
    )
    bundle = composer.compose(ctx)

    text = bundle.system_text
    assert "clases puente" in text.lower() or "puente" in text.lower()
    assert "derived_effects" in text


def test_deletion_module_only_present_when_deletion_is_authorized():
    composer = PromptComposer(variant="modular")
    ctx_without = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION"}),
    )
    bundle_without = composer.compose(ctx_without)

    ctx_with = PromptCompositionContext(
        phase="execution",
        authorized_actions=frozenset({"CREATE_RELATION", "DELETE_RELATION"}),
    )
    bundle_with = composer.compose(ctx_with)

    assert "module_deletion" not in bundle_without.policy_ids
    assert "module_deletion" in bundle_with.policy_ids
    assert "confirmación separada" in bundle_with.system_text.lower()
