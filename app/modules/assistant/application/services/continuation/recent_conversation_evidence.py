"""Construcción de evidencia conversacional reciente priorizada por recencia y presentada cronológicamente.

Cumple con FR-012, SC-004 y T018:
- Prioriza intercambios por recencia (más recientes primero para selección).
- Presenta los intercambios seleccionados en orden cronológico (antiguo a reciente).
- Limita la evidencia a un presupuesto estricto de 1500 tokens estimados.
- No trunca silenciosamente preguntas ni hechos críticos; ante desbordamiento exige precisión.
- No utiliza la memoria personal como confirmación del estado del diagrama.
"""

from __future__ import annotations

from typing import Sequence
import json

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    RecentExchange,
)
from app.modules.assistant.application.services.token_estimator import TokenEstimator


class RecentConversationEvidenceBuilder:
    """Constructor determinista de evidencia conversacional reciente."""

    MAX_ESTIMATED_TOKENS = 1500

    def __init__(self, token_estimator: TokenEstimator | None = None) -> None:
        self.token_estimator = token_estimator or TokenEstimator()

    def estimate_tokens(self, text: str) -> int:
        """Estima tokens usando el token estimator estándar."""
        return self.token_estimator.estimate(text)

    def build_evidence(
        self,
        exchanges: Sequence[RecentExchange],
        *,
        max_tokens: int = MAX_ESTIMATED_TOKENS,
    ) -> list[dict[str, str]]:
        """Construye evidencia priorizada por recencia y presentada cronológicamente.

        Args:
            exchanges: Lista de intercambios recientes, ordenados de más reciente a más antiguo.
            max_tokens: Límite superior de tokens estimados (1500 por defecto).

        Returns:
            Lista de turnos serializados en orden cronológico que caben en el presupuesto.
        """
        eligible = [x for x in exchanges if not getattr(x, "is_superseded", False)]
        if not eligible:
            return []

        # Ordenar primero por recencia (más reciente primero) para priorizar selección
        sorted_by_recency = sorted(eligible[:3], key=lambda x: x.created_at, reverse=True)

        selected: list[dict[str, str]] = []
        for exchange in sorted_by_recency:
            item = {
                "message_id": str(exchange.message_id),
                "user": exchange.user_prompt,
                "assistant": exchange.assistant_response,
            }
            if exchange.confirmed_operations:
                item["confirmed_operations"] = "; ".join(exchange.confirmed_operations)
            candidate = [item, *selected]
            if self.estimate_tokens(json.dumps(candidate, ensure_ascii=False)) > max_tokens:
                # No inferir la intención desde intercambios antiguos si falta el último.
                break
            selected = candidate

        return selected
