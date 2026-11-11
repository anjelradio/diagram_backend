"""Servicio de resolución y consulta de bitácora de auditoría para el asistente."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import logging
import re
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

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

DEFAULT_TIMEZONE = "America/La_Paz"


def resolve_timezone(tz: str | ZoneInfo | None) -> ZoneInfo:
    """Resuelve la zona horaria objetivo, con fallback predeterminado a America/La_Paz."""
    if tz is None:
        return ZoneInfo(DEFAULT_TIMEZONE)
    if isinstance(tz, ZoneInfo):
        return tz
    try:
        return ZoneInfo(str(tz).strip())
    except Exception:
        logger.warning("Zona horaria inválida: %r, usando %s por defecto", tz, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def get_timezone_label(tz: ZoneInfo | str) -> str:
    """Devuelve una etiqueta legible en español para la zona horaria."""
    tz_key = tz.key if isinstance(tz, ZoneInfo) else str(tz)
    if tz_key == "America/La_Paz":
        return "hora de Bolivia"
    if tz_key.upper() in ("UTC", "ETC/UTC"):
        return "hora UTC"
    city = tz_key.split("/")[-1].replace("_", " ")
    return f"hora de {city}"


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
    timezone: str = DEFAULT_TIMEZONE


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
    timezone: str = DEFAULT_TIMEZONE
    timezone_label: str = "hora de Bolivia"
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
        default_timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.audit_repository = audit_repository
        self.member_reader = member_reader
        self.project_repository = project_repository
        self.author_name_reader = author_name_reader
        self.default_timezone = default_timezone

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

    @classmethod
    def resolve_time_range(
        cls,
        time_filter: str | None = None,
        exact_date: str | None = None,
        reference_time: datetime | None = None,
        user_timezone: str | ZoneInfo | None = None,
    ) -> TimeRange:
        """Calcula los límites temporales UTC según el filtro o fecha exacta evaluados en la zona horaria local."""
        tz = resolve_timezone(user_timezone)

        if reference_time is not None:
            if reference_time.tzinfo is None:
                ref_utc = reference_time.replace(tzinfo=timezone.utc)
            else:
                ref_utc = reference_time.astimezone(timezone.utc)
            now_local = ref_utc.astimezone(tz)
        else:
            now_local = datetime.now(tz)
            ref_utc = now_local.astimezone(timezone.utc)

        today_local = now_local.date()

        if exact_date and exact_date.strip():
            raw_date = exact_date.strip()
            # Validar formato ISO YYYY-MM-DD
            try:
                parsed_date = date.fromisoformat(raw_date)
                start_local = datetime.combine(parsed_date, time.min).replace(tzinfo=tz)
                end_local = datetime.combine(parsed_date, time.max).replace(tzinfo=tz)
                since_utc = start_local.astimezone(timezone.utc)
                until_utc = end_local.astimezone(timezone.utc)
                return TimeRange(
                    since=since_utc,
                    until=until_utc,
                    label=f"el {parsed_date.isoformat()}",
                    timezone=tz.key,
                )
            except ValueError:
                logger.warning("Fecha exacta inválida: %r", exact_date)

        if not time_filter or not time_filter.strip():
            return TimeRange(since=None, until=None, label="histórico", timezone=tz.key)

        clean_filter = time_filter.strip().casefold()

        if clean_filter in ("today", "hoy"):
            start_local = datetime.combine(today_local, time.min).replace(tzinfo=tz)
            since_utc = start_local.astimezone(timezone.utc)
            until_utc = ref_utc
            return TimeRange(since=since_utc, until=until_utc, label="hoy", timezone=tz.key)

        if clean_filter in ("yesterday", "ayer"):
            yesterday_local = today_local - timedelta(days=1)
            start_local = datetime.combine(yesterday_local, time.min).replace(tzinfo=tz)
            end_local = datetime.combine(yesterday_local, time.max).replace(tzinfo=tz)
            since_utc = start_local.astimezone(timezone.utc)
            until_utc = end_local.astimezone(timezone.utc)
            return TimeRange(since=since_utc, until=until_utc, label="ayer", timezone=tz.key)

        if clean_filter in ("day_before_yesterday", "anteayer", "antes_de_ayer", "antes de ayer"):
            day_before_local = today_local - timedelta(days=2)
            start_local = datetime.combine(day_before_local, time.min).replace(tzinfo=tz)
            end_local = datetime.combine(day_before_local, time.max).replace(tzinfo=tz)
            since_utc = start_local.astimezone(timezone.utc)
            until_utc = end_local.astimezone(timezone.utc)
            return TimeRange(since=since_utc, until=until_utc, label="anteayer", timezone=tz.key)

        if clean_filter in ("recent_days", "ultimos_dias", "últimos_días", "ultimos dias", "últimos días"):
            start_local = datetime.combine(today_local - timedelta(days=5), time.min).replace(tzinfo=tz)
            since_utc = start_local.astimezone(timezone.utc)
            until_utc = ref_utc
            return TimeRange(since=since_utc, until=until_utc, label="en los últimos días", timezone=tz.key)

        if clean_filter in ("this_week", "esta_semana", "esta semana", "semana"):
            start_local = datetime.combine(today_local - timedelta(days=7), time.min).replace(tzinfo=tz)
            since_utc = start_local.astimezone(timezone.utc)
            until_utc = ref_utc
            return TimeRange(since=since_utc, until=until_utc, label="esta semana", timezone=tz.key)

        return TimeRange(since=None, until=None, label="histórico", timezone=tz.key)

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
        user_timezone: str | ZoneInfo | None = None,
    ) -> AuditQueryResult:
        """Ejecuta la consulta con desambiguación de colaboradores, rango temporal y conversión de zona horaria."""
        active_tz = resolve_timezone(user_timezone or self.default_timezone)
        tz_label = get_timezone_label(active_tz)

        # 1. Resolver temporalidad en zona horaria local (límites convertidos a UTC para DB)
        time_range = self.resolve_time_range(
            time_filter=time_filter,
            exact_date=exact_date,
            reference_time=reference_time,
            user_timezone=active_tz,
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

        # 5. Agrupación jerárquica con conversión a zona horaria local
        # Nivel 1: Fecha local (YYYY-MM-DD)
        # Nivel 2: Clase contenedora o propia (parent_class_name o entity_name)
        # Nivel 3: Lista de eventos detallados con horas locales
        grouped_by_date: dict[str, dict[str, list[dict[str, Any]]]] = {}
        flat_events: list[dict[str, Any]] = []

        for log in logs:
            if log.created_date:
                dt = log.created_date
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(active_tz)
                event_date = local_dt.strftime("%Y-%m-%d")
                local_time_str = local_dt.strftime("%H:%M:%S")
                local_time_display = f"{local_time_str}, {tz_label}"
                created_date_iso = local_dt.isoformat()
                created_date_utc_iso = dt.astimezone(timezone.utc).isoformat()
            else:
                event_date = "Fecha desconocida"
                local_time_str = ""
                local_time_display = ""
                created_date_iso = ""
                created_date_utc_iso = ""

            # Determinar clase de agrupación
            target_class = (
                log.parent_class_name
                or (log.entity_name if log.entity_type == DiagramAuditEntityType.CLASS else "General")
            )

            formatted_event = (
                f"{log.summary} ({local_time_display})"
                if local_time_display and log.summary
                else (log.summary or "")
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
                "local_time": local_time_str,
                "local_time_display": local_time_display,
                "formatted_event": formatted_event,
                "created_date": created_date_iso,
                "created_date_utc": created_date_utc_iso,
                "timezone": active_tz.key,
                "timezone_label": tz_label,
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
            timezone=active_tz.key,
            timezone_label=tz_label,
            is_ambiguous_collaborator=is_ambiguous,
            ambiguity_message=ambiguity_msg,
        )
