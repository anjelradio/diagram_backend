"""Ensamblador de contexto por capas (L0: Estado de Diálogo, L1: Ventana Corta, L2: Memoria Larga)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    RecentExchange,
)
from app.modules.assistant.application.services.token_estimator import TokenEstimator


@dataclass(frozen=True, slots=True)
class AssembledTurnContext:
    """Contexto ensamblado con aislamiento de presupuestos por capa."""

    dialog_state_payload: dict[str, Any] | None
    recent_turns: list[dict[str, Any]]
    summary_context: str
    recent_turns_text: str


class ContextAssembler:
    """Ensambla capas de memoria respetando presupuestos estrictos de tokens."""

    MAX_RECENT_TURNS_TOKENS = 1500

    def __init__(self, token_estimator: TokenEstimator | None = None) -> None:
        self.token_estimator = token_estimator or TokenEstimator()

    def assemble(
        self,
        *,
        dialog_state: Any | None = None,
        recent_exchanges: Sequence[RecentExchange] | None = None,
        summary_context: str = "",
        max_recent_turns: int = 3,
        max_recent_tokens: int = MAX_RECENT_TURNS_TOKENS,
    ) -> AssembledTurnContext:
        """Construye las capas de contexto para el intérprete y el orquestador."""
        dialog_payload: dict[str, Any] | None = None
        if dialog_state is not None:
            if hasattr(dialog_state, "to_dict"):
                dialog_payload = dialog_state.to_dict()
            elif isinstance(dialog_state, dict):
                dialog_payload = dialog_state

        recent_turns: list[dict[str, Any]] = []
        if isinstance(recent_exchanges, (list, tuple)) and recent_exchanges:
            eligible_exchanges = [
                ex for ex in recent_exchanges if not getattr(ex, "is_superseded", False)
            ]
            sorted_exchanges = sorted(
                eligible_exchanges[:max_recent_turns],
                key=lambda x: getattr(x, "created_at", None),
                reverse=True,
            )
            selected: list[dict[str, Any]] = []
            for ex in sorted_exchanges:
                turn = {
                    "message_id": str(ex.message_id),
                    "user": ex.user_prompt,
                    "assistant": ex.assistant_response,
                }
                if ex.assistant_act:
                    turn["assistant_act"] = ex.assistant_act
                if ex.confirmed_operations:
                    turn["confirmed_operations"] = list(ex.confirmed_operations)

                candidate = [turn, *selected]
                if self.token_estimator.estimate(json.dumps(candidate, ensure_ascii=False)) > max_recent_tokens:
                    break
                selected = candidate
            recent_turns = selected

        recent_text_parts: list[str] = []
        for t in recent_turns:
            part = f"- Usuario: {t.get('user', '')}\n- Asistente: {t.get('assistant', '')}"
            if t.get("confirmed_operations"):
                ops = "; ".join(t["confirmed_operations"])
                part += f"\n  (Operaciones aplicadas: {ops})"
            recent_text_parts.append(part)
        recent_turns_text = "\n\n".join(recent_text_parts)

        return AssembledTurnContext(
            dialog_state_payload=dialog_payload,
            recent_turns=recent_turns,
            summary_context=summary_context.strip(),
            recent_turns_text=recent_turns_text,
        )
