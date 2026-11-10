from __future__ import annotations

import re
from uuid import UUID, uuid4

from app.modules.assistant.domain.exceptions import InvalidAgentUserMemoryException


class AgentUserMemory:
    """Resumen Markdown privado de un usuario dentro de un proyecto."""

    MAX_SUMMARY_CONTEXT_CHARS = 24_000
    PROMPT_EXCERPT_CHARS = 600
    RESPONSE_EXCERPT_CHARS = 1_200
    _URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

    def __init__(
        self, *, id: UUID, user_id: str, project_id: UUID, summary_context: str
    ) -> None:
        normalized_summary = self._normalize_summary(summary_context)
        self._validate_summary(normalized_summary)
        self.id = id
        self.user_id = user_id
        self.project_id = project_id
        self.summary_context = normalized_summary

    @classmethod
    def create(
        cls, *, user_id: str, project_id: UUID, summary_context: str
    ) -> AgentUserMemory:
        return cls(
            id=uuid4(),
            user_id=user_id,
            project_id=project_id,
            summary_context=summary_context,
        )

    def update_summary_context(self, summary_context: str) -> None:
        """Reemplaza el contexto por una versión Markdown válida y acotada."""
        normalized_summary = self._normalize_summary(summary_context)
        self._validate_summary(normalized_summary)
        self.summary_context = normalized_summary

    def append_interaction(
        self,
        prompt: str,
        response_markdown: str,
        *,
        confirmed_operations: list[dict[str, object]] | None = None,
    ) -> None:
        """Añade extractos y solo referencias a operaciones confirmadas por use cases."""
        prompt_excerpt = self._safe_excerpt(prompt, self.PROMPT_EXCERPT_CHARS)
        response_excerpt = self._safe_excerpt(
            response_markdown, self.RESPONSE_EXCERPT_CHARS
        )
        if not prompt_excerpt or not response_excerpt:
            raise InvalidAgentUserMemoryException(
                "La interacción de memoria debe contener solicitud y respuesta."
            )
        confirmed_lines: list[str] = []
        for operation in (confirmed_operations or [])[:12]:
            if operation.get("status") != "applied":
                continue
            kind = self._safe_excerpt(str(operation.get("action_kind") or "cambio"), 80)
            refs = operation.get("entity_refs")
            identifiers = []
            if isinstance(refs, list):
                for ref in refs[:6]:
                    if isinstance(ref, dict) and ref.get("type") and ref.get("id"):
                        identifiers.append(
                            self._safe_excerpt(f"{ref['type']}:{ref['id']}", 100)
                        )
            confirmation = f"{kind}: {', '.join(identifiers)}" if identifiers else kind
            confirmed_lines.append(f"- Confirmado: {confirmation}")
        confirmed_section = "\n".join(confirmed_lines)
        interaction = (
            "## Interacciones recientes\n"
            f"- Solicitud: {prompt_excerpt}\n"
            + (f"{confirmed_section}\n" if confirmed_section else "")
            + f"- Respuesta del asistente: {response_excerpt}"
        )
        combined = (
            f"{self.summary_context.rstrip()}\n\n{interaction}"
            if self.summary_context.strip()
            else interaction
        )
        if len(combined) > self.MAX_SUMMARY_CONTEXT_CHARS:
            combined = combined[: self.MAX_SUMMARY_CONTEXT_CHARS].rstrip()
        self.update_summary_context(combined)

    @classmethod
    def _safe_excerpt(cls, value: str, limit: int) -> str:
        normalized = " ".join(value.split()) if isinstance(value, str) else ""
        normalized = cls._URL_PATTERN.sub("[URL omitida]", normalized)
        return normalized[:limit]

    @classmethod
    def _validate_summary(cls, summary_context: str) -> None:
        if (
            not isinstance(summary_context, str)
            or not summary_context.strip()
            or len(summary_context) > cls.MAX_SUMMARY_CONTEXT_CHARS
        ):
            raise InvalidAgentUserMemoryException()

    @classmethod
    def _normalize_summary(cls, summary_context: str) -> str:
        if not isinstance(summary_context, str):
            raise InvalidAgentUserMemoryException()
        return cls._URL_PATTERN.sub("[URL omitida]", summary_context.strip())
