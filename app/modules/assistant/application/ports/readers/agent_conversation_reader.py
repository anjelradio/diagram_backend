"""Contratos para lectura paginada y acotada de conversaciones del proyecto."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConversationExcerpt:
    """Vista reducida y segura de un mensaje en el historial."""

    message_id: UUID
    created_at: str
    author: str
    prompt_excerpt: str
    response_excerpt: str
    status: str
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationPage:
    """Página de extractos con control de cursor y truncamiento de presupuesto."""

    items: tuple[ConversationExcerpt, ...]
    has_more: bool
    next_cursor: str | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class ConversationMessageDetail:
    """Detalle seguro y acotado de un mensaje con operaciones confirmadas."""

    message_id: UUID
    created_at: str
    author: str
    prompt_excerpt: str
    response_excerpt: str
    confirmed_operations: tuple[str, ...]
    truncated: bool
    status: str = "completed"
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class RecentExchange:
    """Intercambio conversacional reciente completo y validado."""

    message_id: UUID
    created_at: datetime
    user_prompt: str
    assistant_response: str
    confirmed_operations: tuple[str, ...] = ()
    status: str = "completed"
    outcome: str | None = None
    kind: str | None = None
    assistant_act: str | None = None
    is_superseded: bool = False
    proposals: tuple[dict[str, Any], ...] = ()
    notion_tasks: tuple[dict[str, Any], ...] = ()


class AgentConversationReader(ABC):
    """Puerto de lectura acotada de mensajes de conversación."""

    @abstractmethod
    def read_conversation_page(
        self,
        *,
        project_id: UUID,
        user_id: str | None = None,
        query: str | None = None,
        before: datetime | None = None,
        limit: int = 5,
        cursor: str | None = None,
        max_total_chars: int = 4000,
    ) -> ConversationPage:
        """Obtiene una página acotada de mensajes completados filtrados."""

    @abstractmethod
    def read_message_detail(
        self,
        *,
        project_id: UUID,
        message_id: UUID,
        user_id: str | None = None,
        max_total_chars: int = 4000,
    ) -> ConversationMessageDetail | None:
        """Obtiene el detalle seguro de un mensaje completado."""

    @abstractmethod
    def get_recent_exchanges(
        self,
        *,
        project_id: UUID,
        user_id: str,
        exclude_message_id: UUID | None = None,
        before: datetime | None = None,
        limit: int = 3,
        exclude_superseded: bool = False,
    ) -> list[RecentExchange]:
        """Recupera hasta limit intercambios recientes completos del mismo usuario y proyecto."""

