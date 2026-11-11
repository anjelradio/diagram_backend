"""Servicio de resolución y consulta de bitácora de auditoría para el asistente."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import logging
import re
from typing import Any
from uuid import UUID

from app.modules.collaboration.application.ports.readers.project_member_list_reader import (
    ProjectMemberListReader,
)
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.repositories.diagram_audit_log_repository import (
    DiagramAuditLogRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.modules.assistant.application.ports.agent_author_name_reader import (
    AgentAuthorNameReader,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollaboratorMatch:
    user_id: str
    name: str
    email: str | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class TimeRange:
    since: datetime | None
    until: datetime | None
    label: str


@dataclass(frozen=True, slots=True)
class GroupedAuditOperation:
    id: str
    user_name: str
    user_id: str
    actor_type: str
    action: str
    entity_type: str
    entity_name: str
    parent_class_name: str | None
    summary: str
    created_date: str
    payload_before: dict[str, Any] | None = None
    payload_after: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AuditQueryResult:
    total_events: int
    grouped_by_date: dict[str, dict[str, list[dict[str, Any]]]]
    collaborators_matched: list[str]
    time_range_label: str
    events: list[dict[str, Any]]
    is_ambiguous_collaborator: bool = False
    ambiguity_message: str | None = None


class AuditQueryService:
    """Servicio para interpretar y ejecutar consultas sobre DiagramAuditLog."""

    def __init__(
        self,
        audit_repository: DiagramAuditLogRepository,
        member_reader: ProjectMemberListReader | None = None,
        project_repository: ProjectRepository | None = None,
        author_name_reader: AgentAuthorNameReader | None = None,
    ) -> None:
        self.audit_repository = audit_repository
        self.member_reader = member_reader
        self.project_repository = project_repository
        self.author_name_reader = author_name_reader

    def resolve_collaborators(
        self,
        project_id: UUID,
        collaborator_name: str | None,
    ) -> list[CollaboratorMatch]:
        """Resuelve usuarios/colaboradores que coincidan con el nombre buscado."""
        if not collaborator_name or not collaborator_name.strip():
            return []

        search_term = collaborator_name.strip().casefold()
        candidates: dict[str, CollaboratorMatch] = {}

        # 1. Buscar en miembros del proyecto si hay lector de miembros
        if self.member_reader is not None:
            try:
                members = self.member_reader.list_members(project_id)
                for m in members:
                    m_name = (m.name or "").strip()
                    m_email = (m.email or "").strip()
                    # Coincidencia por nombre completo, primer nombre o email
                    if (
                        search_term in m_name.casefold()
                        or search_term in m_email.casefold()
                        or any(part.casefold() == search_term for part in m_name.split())
                    ):
                        candidates[m.user_id] = CollaboratorMatch(
                            user_id=m.user_id,
                            name=m_name or m.user_id,
                            email=m_email or None,
                            role=m.role.value if hasattr(m.role, "value") else str(m.role),
                        )
            except Exception as exc:
                logger.warning("Error leyendo miembros del proyecto: %s", exc)

        # 2. Buscar propietario del proyecto si no está ya en la lista
        if self.project_repository is not None:
            try:
                proj = self.project_repository.find_by_id(project_id)
                if proj and proj.owner_id and proj.owner_id not in candidates:
                    owner_name = proj.owner_id
                    if self.author_name_reader is not None:
                        names = self.author_name_reader.find_names({proj.owner_id})
                        if proj.owner_id in names:
                            owner_name = names[proj.owner_id]
                    if search_term in owner_name.casefold() or any(
                        part.casefold() == search_term for part in owner_name.split()
                    ):
                        candidates[proj.owner_id] = CollaboratorMatch(
                            user_id=proj.owner_id,
                            name=owner_name,
                            role="owner",
                        )
            except Exception as exc:
                logger.warning("Error leyendo propietario del proyecto: %s", exc)

        return list(candidates.values())

    @staticmethod
    def resolve_time_range(
        time_filter: str | None = None,
        exact_date: str | None = None,
        reference_time: datetime | None = None,
    ) -> TimeRange:
        """Calcula los límites temporales UTC según el filtro o fecha exacta."""
        now = reference_time or datetime.now(timezone.utc)
        today = now.date()

        if exact_date and exact_date.strip():
            raw_date = exact_date.strip()
            # Validar formato ISO YYYY-MM-DD
            try:
                parsed_date = date.fromisoformat(raw_date)
                since = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
                until = datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)
                return TimeRange(since=since, until=until, label=f"el {parsed_date.isoformat()}")
            except ValueError:
                logger.warning("Fecha exacta inválida: %r", exact_date)

        if not time_filter or not time_filter.strip():
            return TimeRange(since=None, until=None, label="histórico")

        clean_filter = time_filter.strip().casefold()

        if clean_filter in ("today", "hoy"):
            since = datetime.combine(today, time.min, tzinfo=timezone.utc)
            return TimeRange(since=since, until=now, label="hoy")

        if clean_filter in ("yesterday", "ayer"):
            yesterday = today - timedelta(days=1)
            since = datetime.combine(yesterday, time.min, tzinfo=timezone.utc)
            until = datetime.combine(yesterday, time.max, tzinfo=timezone.utc)
            return TimeRange(since=since, until=until, label="ayer")

        if clean_filter in ("day_before_yesterday", "anteayer", "antes_de_ayer", "antes de ayer"):
            day_before = today - timedelta(days=2)
            since = datetime.combine(day_before, time.min, tzinfo=timezone.utc)
            until = datetime.combine(day_before, time.max, tzinfo=timezone.utc)
            return TimeRange(since=since, until=until, label="anteayer")

        if clean_filter in ("recent_days", "ultimos_dias", "últimos_días", "ultimos dias", "últimos días"):
            since = datetime.combine(today - timedelta(days=5), time.min, tzinfo=timezone.utc)
            return TimeRange(since=since, until=now, label="en los últimos días")

        if clean_filter in ("this_week", "esta_semana", "esta semana", "semana"):
            since = datetime.combine(today - timedelta(days=7), time.min, tzinfo=timezone.utc)
            return TimeRange(since=since, until=now, label="esta semana")

        return TimeRange(since=None, until=None, label="histórico")

    def execute_query(
        self,
        *,
        project_id: UUID,
        collaborator_name: str | None = None,
        entity_name: str | None = None,
        parent_class_name: str | None = None,
        entity_type: str | None = None,
        action: str | None = None,
        time_filter: str | None = None,
        exact_date: str | None = None,
        limit: int = 50,
        reference_time: datetime | None = None,
    ) -> AuditQueryResult:
        """Ejecuta la consulta con desambiguación de colaboradores y rango temporal."""
        # 1. Resolver temporalidad
        time_range = self.resolve_time_range(
            time_filter=time_filter,
            exact_date=exact_date,
            reference_time=reference_time,
        )

        # 2. Resolver colaborador
        user_id_to_filter: str | None = None
        user_search_to_filter: str | None = None
        collaborator_matches = self.resolve_collaborators(project_id, collaborator_name)
        matched_names: list[str] = [m.name for m in collaborator_matches]
        is_ambiguous = False
        ambiguity_msg: str | None = None

        if collaborator_name and collaborator_name.strip():
            if len(collaborator_matches) == 1:
                user_id_to_filter = collaborator_matches[0].user_id
            elif len(collaborator_matches) > 1:
                # Si hay múltiples personas con el mismo nombre de pila
                is_ambiguous = True
                names_str = ", ".join(f"'{m.name}'" for m in collaborator_matches)
                ambiguity_msg = (
                    f"Se encontraron varios colaboradores que coinciden con '{collaborator_name}': {names_str}."
                )
                # Usar búsqueda por texto de usuario para abarcar los registros
                user_search_to_filter = collaborator_name.strip()
            else:
                # Si no está en la lista de miembros activa, buscar en user_name de la bitácora
                user_search_to_filter = collaborator_name.strip()

        # 3. Parsear enums
        parsed_entity_type: DiagramAuditEntityType | None = None
        if entity_type and entity_type.strip():
            val = entity_type.strip().upper()
            try:
                parsed_entity_type = DiagramAuditEntityType(val)
            except ValueError:
                logger.warning("entity_type desconocido: %r", entity_type)

        parsed_action: DiagramAuditAction | None = None
        if action and action.strip():
            act_val = action.strip().upper()
            try:
                parsed_action = DiagramAuditAction(act_val)
            except ValueError:
                logger.warning("action desconocida: %r", action)

        # 4. Consultar repositorio
        logs = self.audit_repository.list_by_project(
            project_id=project_id,
            user_id=user_id_to_filter,
            user_search=user_search_to_filter,
            entity_name=entity_name,
            parent_class_name=parent_class_name,
            entity_type=parsed_entity_type,
            action=parsed_action,
            since=time_range.since,
            until=time_range.until,
            limit=limit,
        )

        # 5. Agrupación jerárquica
        # Nivel 1: Fecha (YYYY-MM-DD)
        # Nivel 2: Clase contenedora o propia (parent_class_name o entity_name)
        # Nivel 3: Lista de eventos detallados
        grouped_by_date: dict[str, dict[str, list[dict[str, Any]]]] = {}
        flat_events: list[dict[str, Any]] = []

        for log in logs:
            event_date = (
                log.created_date.strftime("%Y-%m-%d")
                if log.created_date
                else "Fecha desconocida"
            )
            # Determinar clase de agrupación
            target_class = (
                log.parent_class_name
                or (log.entity_name if log.entity_type == DiagramAuditEntityType.CLASS else "General")
            )

            event_dict: dict[str, Any] = {
                "id": str(log.id),
                "user_id": log.user_id,
                "user_name": log.user_name,
                "actor_type": log.actor_type.value,
                "action": log.action.value,
                "entity_type": log.entity_type.value,
                "entity_name": log.entity_name,
                "parent_class_name": log.parent_class_name,
                "use_case": log.use_case,
                "summary": log.summary,
                "created_date": log.created_date.isoformat() if log.created_date else "",
                "payload_before": log.payload_before,
                "payload_after": log.payload_after,
            }

            flat_events.append(event_dict)

            if event_date not in grouped_by_date:
                grouped_by_date[event_date] = {}
            if target_class not in grouped_by_date[event_date]:
                grouped_by_date[event_date][target_class] = []

            grouped_by_date[event_date][target_class].append(event_dict)

        return AuditQueryResult(
            total_events=len(flat_events),
            grouped_by_date=grouped_by_date,
            collaborators_matched=matched_names,
            time_range_label=time_range.label,
            events=flat_events,
            is_ambiguous_collaborator=is_ambiguous,
            ambiguity_message=ambiguity_msg,
        )
