"""Adaptador SQLModel para lectura paginada y acotada de conversaciones."""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from uuid import UUID

from sqlmodel import Session, select

from app.modules.assistant.application.ports.agent_author_name_reader import (
    AgentAuthorNameReader,
)
from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    AgentConversationReader,
    ConversationExcerpt,
    ConversationMessageDetail,
    ConversationPage,
    RecentExchange,
)
from app.modules.assistant.application.services.memory_evidence import (
    extract_confirmed_operations,
)
from app.modules.assistant.infrastructure.persistence.models.agent_continuation_model import (
    AgentContinuationModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_author_name_reader import (
    SQLModelAgentAuthorNameReader,
)


def _extract_outcome(record: AgentMessageModel) -> str | None:
    if isinstance(record.plan, dict):
        if "outcome" in record.plan and isinstance(record.plan["outcome"], str):
            return record.plan["outcome"]
        metadata = record.plan.get("metadata")
        if isinstance(metadata, dict) and "outcome" in metadata and isinstance(metadata["outcome"], str):
            return metadata["outcome"]
    return None


def _extract_assistant_act(record: AgentMessageModel) -> str | None:
    if isinstance(record.plan, dict):
        if "assistant_act" in record.plan and isinstance(record.plan["assistant_act"], str):
            return record.plan["assistant_act"]
        if record.plan.get("outcome") == "awaiting_input":
            return "elicit_slots"
        if record.plan.get("kind") == "visual_clarification":
            return "visual_clarification"
    return None


def _compute_filter_fingerprint(
    query: str | None,
    user_id: str | None,
    before: datetime | None,
) -> str:
    q = (query or "").strip().lower()
    u = user_id or ""
    b = before.isoformat() if before else ""
    raw = f"{q}|{u}|{b}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class SQLModelAgentConversationReader(AgentConversationReader):
    """Lector optimizado de mensajes de conversación por proyecto."""

    def __init__(
        self,
        session: Session,
        author_reader: AgentAuthorNameReader | None = None,
    ) -> None:
        self.session = session
        self.author_reader = author_reader or SQLModelAgentAuthorNameReader(session)

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
        clamped_limit = min(max(limit, 1), 5)
        statement = select(AgentMessageModel).where(
            AgentMessageModel.project_id == project_id,
            AgentMessageModel.deleted_date.is_(None),
            AgentMessageModel.status.in_(["completed", "partial", "failed", "cancelled"]),
            AgentMessageModel.response_markdown.isnot(None),
            AgentMessageModel.response_markdown != "",
        )

        if user_id is not None:
            statement = statement.where(AgentMessageModel.user_id == user_id)

        if before is not None:
            statement = statement.where(AgentMessageModel.created_date < before)

        if query is not None and query.strip():
            # Escapar comodines y dividir en hasta 6 términos
            terms = [t.strip() for t in query.split() if t.strip()][:6]
            for term in terms:
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pattern = f"%{escaped}%"
                statement = statement.where(
                    AgentMessageModel.prompt.like(pattern, escape="\\")
                    | AgentMessageModel.response_markdown.like(pattern, escape="\\")
                )

        current_fingerprint = _compute_filter_fingerprint(query, user_id, before)

        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
                parts = decoded.split("|")
                if len(parts) == 3:
                    fp, ts_str, id_str = parts
                    if fp != current_fingerprint:
                        raise ValueError("Cursor inválido para los filtros suministrados.")
                elif len(parts) == 2:
                    ts_str, id_str = parts
                else:
                    raise ValueError("Formato de cursor desconocido.")

                cursor_dt = datetime.fromisoformat(ts_str)
                cursor_id = UUID(id_str)
                statement = statement.where(
                    (AgentMessageModel.created_date < cursor_dt)
                    | (
                        (AgentMessageModel.created_date == cursor_dt)
                        & (AgentMessageModel.id < cursor_id)
                    )
                )
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("Cursor inválido") from exc

        statement = statement.order_by(
            AgentMessageModel.created_date.desc(),
            AgentMessageModel.id.desc(),
        ).limit(clamped_limit + 1)

        records = self.session.exec(statement).all()
        has_more_records = len(records) > clamped_limit
        page_records = records[:clamped_limit]

        user_ids = {r.user_id for r in page_records if r.user_id}
        author_names = self.author_reader.find_names(user_ids)

        items: list[ConversationExcerpt] = []
        total_chars = 0
        truncated = False
        last_processed_record: AgentMessageModel | None = None

        for record in page_records:
            author = author_names.get(record.user_id) or "Usuario"
            created_at = record.created_date.isoformat() if record.created_date else ""
            prompt_text = record.prompt or ""
            response_text = record.response_markdown or ""
            msg_chars = len(prompt_text) + len(response_text)

            if total_chars + msg_chars <= max_total_chars:
                items.append(
                    ConversationExcerpt(
                        message_id=record.id,
                        created_at=created_at,
                        author=author,
                        prompt_excerpt=prompt_text,
                        response_excerpt=response_text,
                        status=record.status,
                        outcome=_extract_outcome(record),
                    )
                )
                total_chars += msg_chars
                last_processed_record = record
            else:
                remaining = max(0, max_total_chars - total_chars)
                truncated = True
                if len(prompt_text) >= remaining:
                    p_excerpt = prompt_text[:remaining]
                    r_excerpt = ""
                else:
                    p_excerpt = prompt_text
                    r_remaining = remaining - len(prompt_text)
                    r_excerpt = response_text[:r_remaining]

                items.append(
                    ConversationExcerpt(
                        message_id=record.id,
                        created_at=created_at,
                        author=author,
                        prompt_excerpt=p_excerpt,
                        response_excerpt=r_excerpt,
                        status=record.status,
                        outcome=_extract_outcome(record),
                    )
                )
                total_chars = max_total_chars
                last_processed_record = record
                break

        has_more = has_more_records or (truncated and len(items) < len(page_records))
        next_cursor: str | None = None
        if has_more and last_processed_record and last_processed_record.created_date:
            token = f"{current_fingerprint}|{last_processed_record.created_date.isoformat()}|{last_processed_record.id}"
            next_cursor = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")

        return ConversationPage(
            items=tuple(items),
            has_more=has_more,
            next_cursor=next_cursor,
            truncated=truncated,
        )

    def read_message_detail(
        self,
        *,
        project_id: UUID,
        message_id: UUID,
        user_id: str | None = None,
        max_total_chars: int = 4000,
    ) -> ConversationMessageDetail | None:
        statement = select(AgentMessageModel).where(
            AgentMessageModel.id == message_id,
            AgentMessageModel.project_id == project_id,
            AgentMessageModel.deleted_date.is_(None),
            AgentMessageModel.status.in_(["completed", "partial", "failed", "cancelled"]),
            AgentMessageModel.response_markdown.isnot(None),
            AgentMessageModel.response_markdown != "",
        )
        if user_id is not None:
            statement = statement.where(AgentMessageModel.user_id == user_id)

        record = self.session.exec(statement).first()
        if record is None:
            return None

        author_names = (
            self.author_reader.find_names({record.user_id}) if record.user_id else {}
        )
        author = author_names.get(record.user_id) or "Usuario"
        created_at = record.created_date.isoformat() if record.created_date else ""
        prompt_text = record.prompt or ""
        response_text = record.response_markdown or ""

        confirmed_ops = extract_confirmed_operations(record.plan)
        formatted_ops = tuple(op.summary for op in confirmed_ops)

        ops_text = "\n".join(formatted_ops)
        total_chars = len(prompt_text) + len(response_text) + len(ops_text)
        truncated = False

        if total_chars > max_total_chars:
            truncated = True
            remaining = max_total_chars
            ops_budget = min(len(ops_text), 1000)
            text_budget = remaining - ops_budget
            p_budget = text_budget // 2
            r_budget = text_budget - p_budget
            prompt_text = prompt_text[:p_budget]
            response_text = response_text[:r_budget]
            if len(ops_text) > ops_budget:
                formatted_ops = tuple(op[:80] for op in formatted_ops)[:10]

        return ConversationMessageDetail(
            message_id=record.id,
            created_at=created_at,
            author=author,
            prompt_excerpt=prompt_text,
            response_excerpt=response_text,
            confirmed_operations=formatted_ops,
            truncated=truncated,
            status=record.status,
            outcome=_extract_outcome(record),
        )

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
        clamped_limit = min(max(limit, 1), 10)
        statement = select(AgentMessageModel).where(
            AgentMessageModel.project_id == project_id,
            AgentMessageModel.user_id == user_id,
            AgentMessageModel.deleted_date.is_(None),
            AgentMessageModel.status.in_(["completed", "partial"]),
            AgentMessageModel.response_markdown.isnot(None),
            AgentMessageModel.response_markdown != "",
        )

        if exclude_message_id is not None:
            statement = statement.where(AgentMessageModel.id != exclude_message_id)

        if before is not None:
            statement = statement.where(AgentMessageModel.created_date < before)

        statement = statement.order_by(
            AgentMessageModel.created_date.desc(), AgentMessageModel.id.desc()
        ).limit(clamped_limit)
        records = list(self.session.exec(statement).all())

        superseded_msg_ids: set[UUID] = set()
        msg_ids = {r.id for r in records}
        root_ids = {r.root_message_id for r in records if r.root_message_id is not None}
        all_candidate_ids = msg_ids | root_ids
        if all_candidate_ids:
            cont_stmt = select(AgentContinuationModel).where(
                AgentContinuationModel.deleted_date.is_(None),
                (AgentContinuationModel.root_message_id.in_(all_candidate_ids))
                | (AgentContinuationModel.latest_message_id.in_(all_candidate_ids))
                | (AgentContinuationModel.source_plan_message_id.in_(all_candidate_ids)),
            )
            conts = self.session.exec(cont_stmt).all()
            for c in conts:
                if c.close_reason in ("topic_change", "declined", "expired") or c.state in ("declined", "expired"):
                    if c.root_message_id:
                        superseded_msg_ids.add(c.root_message_id)
                    if c.latest_message_id:
                        superseded_msg_ids.add(c.latest_message_id)
                    if c.source_plan_message_id:
                        superseded_msg_ids.add(c.source_plan_message_id)

        exchanges: list[RecentExchange] = []
        for r in records:
            is_sup = r.id in superseded_msg_ids or (r.root_message_id is not None and r.root_message_id in superseded_msg_ids)
            if exclude_superseded and is_sup:
                continue
            ops = tuple(op.summary for op in extract_confirmed_operations(r.plan))
            dialog_state = r.plan.get("dialog_state") if isinstance(r.plan, dict) else None
            raw_proposals = dialog_state.get("proposals") if isinstance(dialog_state, dict) else None
            proposals = tuple(
                proposal for proposal in raw_proposals[:20]
                if isinstance(proposal, dict)
            ) if isinstance(raw_proposals, list) else ()
            exchanges.append(
                RecentExchange(
                    message_id=r.id,
                    created_at=r.created_date,
                    user_prompt=r.prompt or "",
                    assistant_response=r.response_markdown or "",
                    confirmed_operations=ops,
                    status=r.status,
                    outcome=_extract_outcome(r),
                    kind=r.plan.get("kind") if isinstance(r.plan, dict) else None,
                    assistant_act=_extract_assistant_act(r),
                    is_superseded=is_sup,
                    proposals=proposals,
                )
            )
        return exchanges
