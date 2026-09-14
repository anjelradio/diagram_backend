import uuid
import pytest
from unittest.mock import create_autospec

from app.modules.projects.application.services.project_access_policy import (
    ProjectAccessContext,
    ProjectAccessPolicy,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.entities.project_member import ProjectMember
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.modules.projects.domain.repositories.project_member_repository import (
    ProjectMemberRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)


@pytest.fixture
def mock_project_repo():
    return create_autospec(ProjectRepository, instance=True)


@pytest.fixture
def mock_member_repo():
    return create_autospec(ProjectMemberRepository, instance=True)


@pytest.fixture
def access_policy(mock_project_repo, mock_member_repo):
    return ProjectAccessPolicy(
        project_repository=mock_project_repo,
        project_member_repository=mock_member_repo,
    )


def test_resolve_access_owner_success(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    user_id = "user_owner_1"
    project = Project(
        id=project_id,
        owner_id=user_id,
        name="Proyecto Propietario",
    )
    mock_project_repo.find_by_id.return_value = project

    ctx = access_policy.resolve_access(project_id, user_id)

    assert isinstance(ctx, ProjectAccessContext)
    assert ctx.project == project
    assert ctx.access_role == ProjectAccessRole.OWNER
    mock_member_repo.find_by_project_and_user.assert_not_called()


def test_resolve_access_owner_precedence_over_membership(access_policy, mock_project_repo, mock_member_repo):
    """El owner prevalece incluso si existiera una membresía anómala (ej: READER)."""
    project_id = uuid.uuid4()
    user_id = "user_owner_1"
    project = Project(
        id=project_id,
        owner_id=user_id,
        name="Proyecto Propietario",
    )
    mock_project_repo.find_by_id.return_value = project

    ctx = access_policy.resolve_access(project_id, user_id)

    assert ctx.access_role == ProjectAccessRole.OWNER
    mock_member_repo.find_by_project_and_user.assert_not_called()


def test_resolve_access_editor_active(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    owner_id = "user_owner_1"
    editor_id = "user_editor_1"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Proyecto Compartido",
    )
    mock_project_repo.find_by_id.return_value = project

    member = ProjectMember(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=editor_id,
        role=ProjectMemberRole.EDITOR,
        status=ProjectMemberStatus.ACTIVE,
    )
    mock_member_repo.find_by_project_and_user.return_value = member

    ctx = access_policy.resolve_access(project_id, editor_id)

    assert ctx.project == project
    assert ctx.access_role == ProjectAccessRole.EDITOR


def test_resolve_access_reader_active(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    owner_id = "user_owner_1"
    reader_id = "user_reader_1"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Proyecto Compartido",
    )
    mock_project_repo.find_by_id.return_value = project

    member = ProjectMember(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=reader_id,
        role=ProjectMemberRole.READER,
        status=ProjectMemberStatus.ACTIVE,
    )
    mock_member_repo.find_by_project_and_user.return_value = member

    ctx = access_policy.resolve_access(project_id, reader_id)

    assert ctx.project == project
    assert ctx.access_role == ProjectAccessRole.READER


def test_resolve_access_project_not_found(access_policy, mock_project_repo):
    project_id = uuid.uuid4()
    mock_project_repo.find_by_id.return_value = None

    with pytest.raises(ProjectNotFoundException):
        access_policy.resolve_access(project_id, "some_user")


def test_resolve_access_outsider_raises_404(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    project = Project(id=project_id, owner_id="owner_1", name="Proyecto")
    mock_project_repo.find_by_id.return_value = project
    mock_member_repo.find_by_project_and_user.return_value = None

    with pytest.raises(ProjectNotFoundException):
        access_policy.resolve_access(project_id, "stranger_user")


def test_resolve_access_removed_member_raises_404(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    project = Project(id=project_id, owner_id="owner_1", name="Proyecto")
    mock_project_repo.find_by_id.return_value = project

    member = ProjectMember(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id="user_removed",
        role=ProjectMemberRole.READER,
        status=ProjectMemberStatus.REMOVED,
    )
    mock_member_repo.find_by_project_and_user.return_value = member

    with pytest.raises(ProjectNotFoundException):
        access_policy.resolve_access(project_id, "user_removed")


def test_resolve_access_banned_member_raises_404(access_policy, mock_project_repo, mock_member_repo):
    project_id = uuid.uuid4()
    project = Project(id=project_id, owner_id="owner_1", name="Proyecto")
    mock_project_repo.find_by_id.return_value = project

    member = ProjectMember(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id="user_banned",
        role=ProjectMemberRole.READER,
        status=ProjectMemberStatus.BANNED,
    )
    mock_member_repo.find_by_project_and_user.return_value = member

    with pytest.raises(ProjectNotFoundException):
        access_policy.resolve_access(project_id, "user_banned")
