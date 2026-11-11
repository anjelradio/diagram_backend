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


def test_time_range_resolution():
    ref_time = datetime(2026, 11, 10, 15, 30, 0, tzinfo=timezone.utc)

    # Hoy
    tr_today = AuditQueryService.resolve_time_range("today", reference_time=ref_time)
    assert tr_today.since == datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
    assert tr_today.until == ref_time
    assert tr_today.label == "hoy"

    # Ayer
    tr_yesterday = AuditQueryService.resolve_time_range("ayer", reference_time=ref_time)
    assert tr_yesterday.since == datetime(2026, 11, 9, 0, 0, 0, tzinfo=timezone.utc)
    assert tr_yesterday.label == "ayer"

    # Fecha exacta
    tr_exact = AuditQueryService.resolve_time_range(exact_date="2026-11-05")
    assert tr_exact.since == datetime(2026, 11, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert tr_exact.label == "el 2026-11-05"


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
