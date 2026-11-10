"""Pruebas de contratos inmutables de prompting y resolución de dependencias."""

import pytest

from app.modules.assistant.application.services.prompting.prompt_contracts import (
    CircularPolicyDependencyError,
    MissingPolicyDependencyError,
    PromptBundle,
    PromptCompositionContext,
    PromptPolicy,
    resolve_policy_dependencies,
)


def test_prompt_policy_is_immutable_and_validates_fields():
    policy = PromptPolicy(
        id="core_universal",
        version="1.0.0",
        text="Instrucciones núcleo",
        phases=frozenset({"planning", "execution"}),
        capabilities=frozenset({"universal"}),
        dependencies=(),
    )
    assert policy.id == "core_universal"
    assert policy.version == "1.0.0"
    assert "planning" in policy.phases
    assert "universal" in policy.capabilities
    assert policy.dependencies == ()

    with pytest.raises(Exception):
        # Inmutable (frozen)
        policy.text = "Modificado"  # type: ignore


def test_prompt_policy_rejects_empty_id():
    with pytest.raises(ValueError, match="El id de la política no puede estar vacío"):
        PromptPolicy(
            id="",
            version="1.0.0",
            text="Texto",
            phases=frozenset({"planning"}),
            capabilities=frozenset({"universal"}),
            dependencies=(),
        )


def test_resolve_policy_dependencies_topological_order():
    core = PromptPolicy(
        id="core",
        version="1.0.0",
        text="Core universal",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"universal"}),
        dependencies=(),
    )
    exec_phase = PromptPolicy(
        id="phase_execution",
        version="1.0.0",
        text="Phase execution",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"universal"}),
        dependencies=("core",),
    )
    rel = PromptPolicy(
        id="relations",
        version="1.0.0",
        text="Relations rules",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"relations"}),
        dependencies=("phase_execution",),
    )

    catalog = {"core": core, "phase_execution": exec_phase, "relations": rel}
    resolved = resolve_policy_dependencies(catalog, ["relations"])
    resolved_ids = [p.id for p in resolved]
    assert resolved_ids == ["core", "phase_execution", "relations"]


def test_resolve_policy_dependencies_detects_cycles():
    p_a = PromptPolicy(
        id="a",
        version="1.0.0",
        text="A",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"cap_a"}),
        dependencies=("b",),
    )
    p_b = PromptPolicy(
        id="b",
        version="1.0.0",
        text="B",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"cap_b"}),
        dependencies=("a",),
    )

    catalog = {"a": p_a, "b": p_b}
    with pytest.raises(CircularPolicyDependencyError, match="Ciclo detectado"):
        resolve_policy_dependencies(catalog, ["a"])


def test_resolve_policy_dependencies_detects_missing_dependency():
    p_x = PromptPolicy(
        id="x",
        version="1.0.0",
        text="X",
        phases=frozenset({"execution"}),
        capabilities=frozenset({"cap_x"}),
        dependencies=("non_existent",),
    )

    catalog = {"x": p_x}
    with pytest.raises(MissingPolicyDependencyError, match="no existe"):
        resolve_policy_dependencies(catalog, ["x"])


def test_prompt_bundle_is_immutable():
    bundle = PromptBundle.create(
        version="1.0.0",
        policy_ids=("core", "relations"),
        system_text="Instrucciones completas",
    )
    assert bundle.version == "1.0.0"
    assert bundle.policy_ids == ("core", "relations")
    assert bundle.system_text == "Instrucciones completas"
    assert bundle.estimated_tokens > 0

    with pytest.raises(Exception):
        bundle.system_text = "Otro"  # type: ignore
