import uuid
from datetime import datetime, timezone, timedelta
from sqlmodel import Session

from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.use_cases.diagram_class.create_diagram_class import (
    CreateDiagramClassCommand,
    CreateDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.move_diagram_class import (
    MoveDiagramClassCommand,
    MoveDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.rename_diagram_class import (
    RenameDiagramClassCommand,
    RenameDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_attribute.reposition_diagram_attribute import (
    RepositionDiagramAttributeCommand,
    RepositionDiagramAttributeUseCase,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def test_touch_project_on_create_and_rename_class_but_not_on_move(session: Session):
    user_id = "user_test_touch"
    old_time = datetime.now(timezone.utc) - timedelta(hours=5)

    # 1. Crear proyecto inicial con fecha antigua
    project_id = uuid.uuid4()
    project = ProjectModel(
        id=project_id,
        owner_id=user_id,
        name="Proyecto Touch Test",
        modified_date=old_time,
    )
    session.add(project)
    session.commit()

    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    class_repo = SQLModelDiagramClassRepository(session)
    attr_repo = SQLModelDiagramAttributeRepository(session)
    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )

    create_uc = CreateDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=class_repo,
        diagram_attribute_repository=attr_repo,
        uow=uow,
    )

    class_id = uuid.uuid4()
    pk_id = uuid.uuid4()
    cmd = CreateDiagramClassCommand(
        id=class_id,
        project_id=project_id,
        user_id=user_id,
        name="Cliente",
        position_x=100.0,
        position_y=150.0,
        primary_attribute_id=pk_id,
    )

    # Crear clase debe actualizar modified_date
    create_uc.execute(cmd)

    session.refresh(project)
    after_create_time = _as_utc(project.modified_date)
    assert after_create_time > old_time

    # Mover clase NO debe actualizar modified_date
    move_uc = MoveDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=class_repo,
        uow=uow,
    )
    move_cmd = MoveDiagramClassCommand(
        class_id=class_id,
        user_id=user_id,
        position_x=200.0,
        position_y=250.0,
    )
    move_uc.execute(move_cmd)

    session.refresh(project)
    assert _as_utc(project.modified_date) == after_create_time

    # Renombrar clase DEBE actualizar modified_date
    rename_uc = RenameDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=class_repo,
        uow=uow,
    )
    rename_cmd = RenameDiagramClassCommand(
        class_id=class_id,
        user_id=user_id,
        name="ClienteRenombrado",
    )
    rename_uc.execute(rename_cmd)

    session.refresh(project)
    assert _as_utc(project.modified_date) >= after_create_time

