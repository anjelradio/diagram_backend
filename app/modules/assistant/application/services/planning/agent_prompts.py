"""Instrucciones de sistema acotadas para las fases del agente.

Re-exporta las instrucciones canónicas desde el paquete de prompting para
mantener compatibilidad transparente con importaciones existentes.
"""

from app.modules.assistant.application.services.prompting.legacy_prompts import (
    CONTINUATION_RESOLVER_PROMPT,
    FINAL_PROMPT,
    IMAGE_PROMPT,
    PLANNER_PROMPT,
    TOOL_PROMPT,
    VISUAL_EVIDENCE_PROMPT,
    VISUAL_INTENT_PROMPT,
)

__all__ = [
    "CONTINUATION_RESOLVER_PROMPT",
    "FINAL_PROMPT",
    "IMAGE_PROMPT",
    "PLANNER_PROMPT",
    "TOOL_PROMPT",
    "VISUAL_EVIDENCE_PROMPT",
    "VISUAL_INTENT_PROMPT",
]
