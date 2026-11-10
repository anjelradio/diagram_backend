"""Compositor determinista de instrucciones (PromptComposer) sin IO ni routers AI."""

from collections.abc import Mapping

from app.core.config import settings as default_settings
from app.modules.assistant.application.services.prompting.legacy_prompts import (
    CONTINUATION_RESOLVER_PROMPT,
    FINAL_PROMPT,
    IMAGE_PROMPT,
    PLANNER_PROMPT,
    TOOL_PROMPT,
    VISUAL_EVIDENCE_PROMPT,
    VISUAL_INTENT_PROMPT,
)
from app.modules.assistant.application.services.prompting.prompt_catalog import (
    create_default_prompt_catalog,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptBundle,
    PromptCompositionContext,
    PromptPolicy,
    resolve_policy_dependencies,
)


class PromptComposer:
    """Compositor puro de instrucciones por fase y capacidades de tarea.
    
    Admite variante 'legacy' (predeterminada) o 'modular', manteniendo
    invariantes de seguridad y determinismo absoluto en cada inferencia.
    """

    _LEGACY_PROMPT_BY_PHASE = {
        "planning": ("legacy_planner_prompt", PLANNER_PROMPT),
        "execution": ("legacy_tool_prompt", TOOL_PROMPT),
        "synthesis": ("legacy_final_prompt", FINAL_PROMPT),
        "visual_intent": ("legacy_visual_intent_prompt", VISUAL_INTENT_PROMPT),
        "visual_evidence": ("legacy_visual_evidence_prompt", VISUAL_EVIDENCE_PROMPT),
        "continuation": ("legacy_continuation_resolver_prompt", CONTINUATION_RESOLVER_PROMPT),
        "vision_query": ("legacy_image_prompt", IMAGE_PROMPT),
    }

    def __init__(
        self,
        *,
        catalog: Mapping[str, PromptPolicy] | None = None,
        variant: str | None = None,
    ) -> None:
        self.catalog = catalog if catalog is not None else create_default_prompt_catalog()
        self.variant = (variant or getattr(default_settings, "AGENT_PROMPT_VARIANT", "legacy")).lower().strip()

    def compose(self, context: PromptCompositionContext) -> PromptBundle:
        """Compone un paquete inmutable de instrucciones para el contexto dado."""
        if self.variant == "legacy":
            policy_id, text = self._LEGACY_PROMPT_BY_PHASE.get(
                context.phase, ("legacy_tool_prompt", TOOL_PROMPT)
            )
            return PromptBundle.create(
                version="legacy-1.0.0",
                policy_ids=(policy_id,),
                system_text=text,
            )

        # ── Modo Modular ──────────────────────────────────────────────────
        selected_ids: list[str] = ["core_universal"]
        phase_policy_id = f"phase_{context.phase}"
        if phase_policy_id in self.catalog:
            selected_ids.append(phase_policy_id)

        # Inclusión conservadora de módulos en fase de ejecución según acciones autorizadas y capacidades
        if context.phase == "execution":
            actions_str = " ".join(context.authorized_actions).upper()
            caps = context.derived_capabilities

            if "ATTRIBUTE" in actions_str or "attributes" in caps:
                selected_ids.append("module_attributes")

            if (
                "RELATION" in actions_str
                or "relations" in caps
                or any(k in actions_str for k in ("FK", "BRIDGE", "PUENTE", "INTERMEDIA"))
            ):
                selected_ids.append("module_relations")

            if "DELETE" in actions_str or "deletion" in caps:
                selected_ids.append("module_deletion")

            if (
                "SEARCH_PROJECT_CONVERSATION" in actions_str
                or "GET_PROJECT_CONVERSATION_MESSAGE" in actions_str
                or "history" in caps
            ):
                selected_ids.append("module_history")

            if context.has_image_evidence or "visual_align" in caps or "image" in caps:
                selected_ids.append("module_visual_align")

            if context.has_continuation or "continuation" in caps:
                selected_ids.append("module_continuation")
        elif (context.has_continuation or "continuation" in context.derived_capabilities) and "module_continuation" in self.catalog:
            selected_ids.append("module_continuation")

        resolved_policies = resolve_policy_dependencies(self.catalog, selected_ids)
        combined_text = "\n\n".join(policy.text for policy in resolved_policies)
        policy_ids = tuple(policy.id for policy in resolved_policies)

        return PromptBundle.create(
            version="modular-1.0.0",
            policy_ids=policy_ids,
            system_text=combined_text,
        )
