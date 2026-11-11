from datetime import datetime, timezone
import uuid
import pytest

from app.modules.assistant.application.services.audit.audit_query_service import (
    AuditQueryService,
    CollaboratorMatch,
)
from app.modules.collaboration.application.ports.readers.project_member_list_reader import (
    ProjectMemberItem,
    ProjectMemberListReader,
)
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.diagram.domain.entities.diagram_audit_log import DiagramAuditLog
from app.modules.diagram.domain.enums import (
    DiagramAuditAction,
    DiagramAuditActorType,
    DiagramAuditEntityType,
)
from app.modules.diagram.domain.repositories.diagram_audit_log_repository import (
    DiagramAuditLogRepository,
)


class FakeAuditRepo(DiagramAuditLogRepository):
    def __init__(self, logs=None):
        self.logs = logs or []

    def save(self, audit_log: DiagramAuditLog) -> None:
        self.logs.append(audit_log)

    def find_by_id(self, audit_log_id: uuid.UUID) -> DiagramAuditLog | None:
        return next((l for l in self.logs if l.id == audit_log_id), None)

    def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        user_id: str | None = None,
        user_search: str | None = None,
        actor_type=None,
        entity_type=None,
        entity_id=None,
        entity_name: str | None = None,
        parent_class_id=None,
        parent_class_name: str | None = None,
        action=None,
        since=None,
        until=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiagramAuditLog]:
        res = [l for l in self.logs if l.project_id == project_id]
        if user_id:
            res = [l for l in res if l.user_id == user_id]
        if user_search:
            res = [l for l in res if user_search.lower() in l.user_name.lower()]
        if entity_name:
            res = [l for l in res if entity_name.lower() in l.entity_name.lower()]
        if parent_class_name:
            res = [l for l in res if l.parent_class_name and parent_class_name.lower() in l.parent_class_name.lower()]
        if action:
            res = [l for l in res if l.action == action]
        if entity_type:
            res = [l for l in res if l.entity_type == entity_type]
        if since:
            res = [l for l in res if l.created_date >= since]
        if until:
            res = [l for l in res if l.created_date <= until]
        return res[:limit]


class FakeMemberReader(ProjectMemberListReader):
    def __init__(self, members):
        self.members = members

    def list_members(self, project_id, status=None):
        return self.members


def test_time_range_resolution_default_bolivia():
    # 15:30 UTC = 11:30 Bolivia (America/La_Paz, UTC-4)
    ref_time = datetime(2026, 11, 10, 15, 30, 0, tzinfo=timezone.utc)

    # Hoy en Bolivia (2026-11-10 00:00:00-04:00 -> 2026-11-10 04:00:00 UTC)
    tr_today = AuditQueryService.resolve_time_range("today", reference_time=ref_time)
    assert tr_today.since == datetime(2026, 11, 10, 4, 0, 0, tzinfo=timezone.utc)
    assert tr_today.until == ref_time
    assert tr_today.label == "hoy"
    assert tr_today.timezone == "America/La_Paz"

    # Ayer en Bolivia (2026-11-09 00:00:00-04:00 -> 2026-11-09 04:00:00 UTC)
    tr_yesterday = AuditQueryService.resolve_time_range("ayer", reference_time=ref_time)
    assert tr_yesterday.since == datetime(2026, 11, 9, 4, 0, 0, tzinfo=timezone.utc)
    assert tr_yesterday.until == datetime(2026, 11, 10, 3, 59, 59, 999999, tzinfo=timezone.utc)
    assert tr_yesterday.label == "ayer"

    # Anteayer en Bolivia (2026-11-08 00:00:00-04:00 -> 2026-11-08 04:00:00 UTC)
    tr_day_before = AuditQueryService.resolve_time_range("anteayer", reference_time=ref_time)
    assert tr_day_before.since == datetime(2026, 11, 8, 4, 0, 0, tzinfo=timezone.utc)
    assert tr_day_before.until == datetime(2026, 11, 9, 3, 59, 59, 999999, tzinfo=timezone.utc)
    assert tr_day_before.label == "anteayer"

    # Fecha exacta (2026-11-05 00:00:00-04:00 -> 2026-11-05 04:00:00 UTC)
    tr_exact = AuditQueryService.resolve_time_range(exact_date="2026-11-05")
    assert tr_exact.since == datetime(2026, 11, 5, 4, 0, 0, tzinfo=timezone.utc)
    assert tr_exact.until == datetime(2026, 11, 6, 3, 59, 59, 999999, tzinfo=timezone.utc)
    assert tr_exact.label == "el 2026-11-05"


def test_time_range_resolution_custom_timezone():
    ref_time = datetime(2026, 11, 10, 15, 30, 0, tzinfo=timezone.utc)

    # Configuración de zona horaria por usuario a UTC
    tr_utc = AuditQueryService.resolve_time_range(
        "today", reference_time=ref_time, user_timezone="UTC"
    )
    assert tr_utc.since == datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
    assert tr_utc.until == ref_time
    assert tr_utc.timezone == "UTC"


def test_midnight_date_shift_between_utc_and_bolivia():
    """Prueba de eventos próximos a medianoche y cambio de fecha entre UTC y Bolivia.
    
    A las 02:00:00 UTC del 11 de Noviembre:
    En Bolivia (UTC-4) son las 22:00:00 del 10 de Noviembre.
    Por tanto, para un usuario en Bolivia 'hoy' es el 10 de Noviembre.
    """
    proj_id = uuid.uuid4()
    class_id = uuid.uuid4()

    # ref_time: 2026-11-11 02:00:00 UTC (10 de Noviembre 22:00 Bolivia)
    ref_time = datetime(2026, 11, 11, 2, 0, 0, tzinfo=timezone.utc)

    # Evento 1: Creado a las 2026-11-11 01:30:00 UTC (2026-11-10 21:30:00 Bolivia -> 'hoy')
    log_today = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-carlos",
        user_name="Carlos Mendoza",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Casa",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Se creó la clase 'Casa'",
        payload_after={"id": str(class_id), "name": "Casa"},
        created_date=datetime(2026, 11, 11, 1, 30, 0, tzinfo=timezone.utc),
    )

    # Evento 2: Creado a las 2026-11-10 02:30:00 UTC (2026-11-09 22:30:00 Bolivia -> 'ayer')
    log_yesterday = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-carlos",
        user_name="Carlos Mendoza",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Edificio",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Se creó la clase 'Edificio'",
        payload_after={"id": str(class_id), "name": "Edificio"},
        created_date=datetime(2026, 11, 10, 2, 30, 0, tzinfo=timezone.utc),
    )

    service = AuditQueryService(audit_repository=FakeAuditRepo([log_today, log_yesterday]))

    # Consulta 'hoy' desde Bolivia a las 22:00 del 10 de nov
    result_today = service.execute_query(
        project_id=proj_id,
        time_filter="today",
        reference_time=ref_time,
    )
    # Solo debe incluir el evento de hoy (Casa)
    assert result_today.total_events == 1
    assert result_today.events[0]["entity_name"] == "Casa"
    # Debe estar agrupado bajo el día local de Bolivia: 2026-11-10
    assert "2026-11-10" in result_today.grouped_by_date
    assert "2026-11-11" not in result_today.grouped_by_date

    # Consulta 'ayer' desde Bolivia a las 22:00 del 10 de nov
    result_yesterday = service.execute_query(
        project_id=proj_id,
        time_filter="ayer",
        reference_time=ref_time,
    )
    # Solo debe incluir el evento de ayer (Edificio)
    assert result_yesterday.total_events == 1
    assert result_yesterday.events[0]["entity_name"] == "Edificio"
    assert "2026-11-09" in result_yesterday.grouped_by_date


def test_midnight_local_time_formatting_and_grouping():
    """Valida formato de horas local y asignación estricta de días cerca de medianoche."""
    proj_id = uuid.uuid4()
    class_id = uuid.uuid4()

    # Evento A: 23:59:47 Bolivia -> 2026-11-11 03:59:47 UTC
    log_before_midnight = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-ana",
        user_name="Ana Lopez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Casa",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Se creó la clase Casa",
        payload_after={"id": str(class_id), "name": "Casa"},
        created_date=datetime(2026, 11, 11, 3, 59, 47, tzinfo=timezone.utc),
    )

    # Evento B: 00:00:15 Bolivia -> 2026-11-11 04:00:15 UTC
    log_after_midnight = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-ana",
        user_name="Ana Lopez",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Vehiculo",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Se creó la clase Vehiculo",
        payload_after={"id": str(class_id), "name": "Vehiculo"},
        created_date=datetime(2026, 11, 11, 4, 0, 15, tzinfo=timezone.utc),
    )

    service = AuditQueryService(
        audit_repository=FakeAuditRepo([log_before_midnight, log_after_midnight])
    )
    result = service.execute_query(project_id=proj_id)

    assert result.total_events == 2
    assert result.timezone == "America/La_Paz"
    assert result.timezone_label == "hora de Bolivia"

    # Evento A pertenece al 10 de noviembre en Bolivia a las 23:59:47
    assert "2026-11-10" in result.grouped_by_date
    event_a = result.grouped_by_date["2026-11-10"]["Casa"][0]
    assert event_a["local_time"] == "23:59:47"
    assert event_a["local_time_display"] == "23:59:47, hora de Bolivia"
    assert event_a["formatted_event"] == "Se creó la clase Casa (23:59:47, hora de Bolivia)"

    # Evento B pertenece al 11 de noviembre en Bolivia a las 00:00:15
    assert "2026-11-11" in result.grouped_by_date
    event_b = result.grouped_by_date["2026-11-11"]["Vehiculo"][0]
    assert event_b["local_time"] == "00:00:15"
    assert event_b["local_time_display"] == "00:00:15, hora de Bolivia"
    assert event_b["formatted_event"] == "Se creó la clase Vehiculo (00:00:15, hora de Bolivia)"


def test_collaborator_resolution():
    proj_id = uuid.uuid4()
    members = [
        ProjectMemberItem(
            id=uuid.uuid4(),
            user_id="usr-juan",
            name="Juan Pérez",
            email="juan@test.com",
            image=None,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        ),
        ProjectMemberItem(
            id=uuid.uuid4(),
            user_id="usr-maria",
            name="María Gómez",
            email="maria@test.com",
            image=None,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        ),
    ]
    service = AuditQueryService(
        audit_repository=FakeAuditRepo(),
        member_reader=FakeMemberReader(members),
    )

    matches = service.resolve_collaborators(proj_id, "Juan")
    assert len(matches) == 1
    assert matches[0].user_id == "usr-juan"
    assert matches[0].name == "Juan Pérez"


def test_audit_query_grouping():
    proj_id = uuid.uuid4()
    class_id = uuid.uuid4()
    log1 = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-carlos",
        user_name="Carlos Mendoza",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.CLASS,
        entity_id=class_id,
        entity_name="Producto",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_CLASS",
        summary="Creó la clase Producto",
        payload_after={"id": str(class_id), "name": "Producto"},
        created_date=datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc),
    )
    attr_id = uuid.uuid4()
    log2 = DiagramAuditLog.record(
        project_id=proj_id,
        user_id="usr-carlos",
        user_name="Carlos Mendoza",
        actor_type=DiagramAuditActorType.USER,
        entity_type=DiagramAuditEntityType.ATTRIBUTE,
        entity_id=attr_id,
        entity_name="precio",
        parent_class_id=class_id,
        parent_class_name="Producto",
        action=DiagramAuditAction.CREATE,
        use_case="CREATE_ATTRIBUTE",
        summary="Agregó el atributo precio a Producto",
        payload_after={"id": str(attr_id), "name": "precio", "type": "float"},
        created_date=datetime(2026, 11, 10, 10, 5, 0, tzinfo=timezone.utc),
    )

    service = AuditQueryService(audit_repository=FakeAuditRepo([log1, log2]))
    result = service.execute_query(
        project_id=proj_id,
        collaborator_name="Carlos",
        time_filter="today",
        reference_time=datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert result.total_events == 2
    assert "2026-11-10" in result.grouped_by_date
    assert "Producto" in result.grouped_by_date["2026-11-10"]
    events_in_prod = result.grouped_by_date["2026-11-10"]["Producto"]
    assert len(events_in_prod) == 2
