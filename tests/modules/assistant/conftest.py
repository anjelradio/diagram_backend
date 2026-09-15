import uuid
import pytest
from sqlmodel import Session

from app.core.security.auth import AuthUser
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser
from tests.modules.diagram.conftest import (  # noqa: F401
    banned_user,
    editor_user,
    owner_user,
    reader_user,
    removed_user,
    stranger_user,
    test_project,
)


@pytest.fixture
def second_editor_user() -> AuthUser:
    return AuthUser(user_id="user_editor_2", email="editor2@test.com")


@pytest.fixture
def collaborative_project(
    session: Session,
    owner_user: AuthUser,
    editor_user: AuthUser,
    second_editor_user: AuthUser,
    reader_user: AuthUser,
) -> ProjectModel:
    users = [
        BetterAuthUser(id=owner_user.user_id, name="Owner", email=owner_user.email),
        BetterAuthUser(id=editor_user.user_id, name="Editor 1", email=editor_user.email),
        BetterAuthUser(id=second_editor_user.user_id, name="Editor 2", email=second_editor_user.email),
        BetterAuthUser(id=reader_user.user_id, name="Reader", email=reader_user.email),
    ]
    for u in users:
        existing = session.get(BetterAuthUser, u.id)
        if not existing:
            session.add(u)
    session.flush()

    project = ProjectModel(
        id=uuid.uuid4(),
        owner_id=owner_user.user_id,
        name="Proyecto Colaborativo",
        description="Proyecto con multiples editores",
    )
    session.add(project)
    session.flush()

    members = [
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=editor_user.user_id,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        ),
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=second_editor_user.user_id,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        ),
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=reader_user.user_id,
            role=ProjectMemberRole.READER,
            status=ProjectMemberStatus.ACTIVE,
        ),
    ]
    for m in members:
        session.add(m)

    session.commit()
    session.refresh(project)
    return project
