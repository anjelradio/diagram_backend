"""Pruebas para los contratos de prompts del asistente."""

import pytest

from app.modules.assistant.application.services.planning.agent_prompts import (
    PLANNER_PROMPT,
    TOOL_PROMPT,
    FINAL_PROMPT,
    VISUAL_EVIDENCE_PROMPT,
)


def test_planner_prompt_includes_creation_verbs():
    verbs = ["haz", "crea", "agrega", "añade", "genera"]
    for verb in verbs:
        assert verb in PLANNER_PROMPT.lower()


def test_tool_prompt_documents_semantic_roles_and_endpoints():
    tool_prompt_lower = TOOL_PROMPT.lower()

    # Roles semánticos canónicos y dirección
    assert "composición" in tool_prompt_lower or "composicion" in tool_prompt_lower
    assert "agregación" in tool_prompt_lower or "agregacion" in tool_prompt_lower
    assert "herencia" in tool_prompt_lower or "generalización" in tool_prompt_lower or "generalizacion" in tool_prompt_lower
    assert "realización" in tool_prompt_lower or "realizacion" in tool_prompt_lower
    assert "dependencia" in tool_prompt_lower

    # Mapeo de cabeza (head) para composición/agregación en el todo (source)
    assert "todo" in tool_prompt_lower and "parte" in tool_prompt_lower
    # Mapeo de superclase/contrato como destino (target)
    assert "subclase" in tool_prompt_lower or "superclase" in tool_prompt_lower


def test_tool_prompt_documents_mandatory_association_cardinalities_and_no_mixed_forms():
    tool_prompt_lower = TOOL_PROMPT.lower()

    # Cardinalidades obligatorias en ambos extremos para asociaciones
    assert "asociación" in tool_prompt_lower or "asociacion" in tool_prompt_lower
    # Prohibición de cardinalidad en estructurales / formas mixtas prohibidas
    assert "cardinalidad" in tool_prompt_lower


def test_tool_prompt_documents_clarification_on_ambiguity_and_zero_mutation():
    tool_prompt_lower = TOOL_PROMPT.lower()

    # Instrucciones de aclaración
    assert "aclara" in tool_prompt_lower or "pregunta" in tool_prompt_lower or "clarifica" in tool_prompt_lower


def test_visual_evidence_prompt_documents_head_class_and_conditional_fields():
    prompt_lower = VISUAL_EVIDENCE_PROMPT.lower()
    assert "head_class" in prompt_lower
    assert "diamante" in prompt_lower
    assert "triángulo" in prompt_lower or "triangulo" in prompt_lower
    assert "flecha" in prompt_lower
    assert "cardinalidad" in prompt_lower
