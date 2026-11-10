from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.modules.projects.application.ports.providers.project_image_storage_provider import (
    ProjectImageStorageProvider,
)
from app.modules.projects.application.use_cases.project.update_project_thumbnail import (
    UpdateProjectThumbnailUseCase,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.infrastructure.db.base_model import utc_now


class MockProjectImageStorageProvider(ProjectImageStorageProvider):
    def __init__(self, secure_url: str = "https://res.cloudinary.com/demo/image/upload/diagrama/test.jpg"):
        self.secure_url = secure_url
        self.upload_called_count = 0
        self.last_uploaded_id: str | None = None
        self.delete_called_count = 0

    async def upload_thumbnail(self, image_data: bytes, *, project_id: str) -> str:
        self.upload_called_count += 1
        self.last_uploaded_id = project_id
        return self.secure_url

    async def delete_thumbnail(self, *, project_id: str) -> None:
        self.delete_called_count += 1


class MockProjectRepository:
    def __init__(self, project: Project | None = None):
        self.project = project
        self.save_called = False

    async def get_by_id(self, project_id):
        if self.project and str(self.project.id) == str(project_id):
            return self.project
        return None

    async def save(self, project: Project) -> Project:
        self.save_called = True
        self.project = project
        return project


class MockProjectAccessChecker:
    def __init__(self, can_edit: bool = True):
        self._can_edit = can_edit

    async def can_edit_project(self, project_id, user_id: str) -> bool:
        return self._can_edit


class MockDiagramClassRepository:
    def __init__(self, class_count: int = 0):
        self.class_count = class_count

    def list_by_project_id(self, project_id):
        return ["fake-class"] if self.class_count > 0 else []


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_first_thumbnail_upload_calls_cloudinary_and_persists():
    project_id = uuid4()
    owner_id = "user-123"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Sistema de Ventas",
        thumbnail_url=None,
        thumbnail_updated_at=None,
    )
    repo = MockProjectRepository(project)
    storage = MockProjectImageStorageProvider()
    access_checker = MockProjectAccessChecker(can_edit=True)

    use_case = UpdateProjectThumbnailUseCase(
        project_repository=repo,
        image_storage_provider=storage,
        access_checker=access_checker,
    )

    image_bytes = b"fake-jpeg-bytes"
    result = await use_case.execute(
        project_id=project_id,
        user_id=owner_id,
        image_data=image_bytes,
    )

    assert result["updated"] is True
    assert result["thumbnail_url"] == storage.secure_url
    assert result["thumbnail_updated_at"] is not None
    assert storage.upload_called_count == 1
    assert repo.save_called is True
    assert project.thumbnail_url == storage.secure_url


async def test_thumbnail_upload_within_5_minutes_is_skipped_and_not_sent_to_cloudinary():
    project_id = uuid4()
    owner_id = "user-123"
    recent_time = utc_now() - timedelta(minutes=2)  # hace 2 minutos
    existing_url = "https://res.cloudinary.com/demo/image/upload/diagrama/previous.jpg"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Sistema de Ventas",
        thumbnail_url=existing_url,
        thumbnail_updated_at=recent_time,
    )
    repo = MockProjectRepository(project)
    storage = MockProjectImageStorageProvider()
    access_checker = MockProjectAccessChecker(can_edit=True)

    use_case = UpdateProjectThumbnailUseCase(
        project_repository=repo,
        image_storage_provider=storage,
        access_checker=access_checker,
    )

    image_bytes = b"new-fake-jpeg-bytes"
    result = await use_case.execute(
        project_id=project_id,
        user_id=owner_id,
        image_data=image_bytes,
    )

    # Debe omitirse la subida a Cloudinary y mantenerse la imagen previa
    assert result["updated"] is False
    assert result["thumbnail_url"] == existing_url
    assert result["thumbnail_updated_at"] == recent_time
    assert storage.upload_called_count == 0
    assert repo.save_called is False


async def test_thumbnail_upload_after_5_minutes_proceeds_and_replaces_image():
    project_id = uuid4()
    owner_id = "user-123"
    old_time = utc_now() - timedelta(minutes=6)  # hace 6 minutos
    old_url = "https://res.cloudinary.com/demo/image/upload/diagrama/old.jpg"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Sistema de Ventas",
        thumbnail_url=old_url,
        thumbnail_updated_at=old_time,
    )
    repo = MockProjectRepository(project)
    storage = MockProjectImageStorageProvider(
        secure_url="https://res.cloudinary.com/demo/image/upload/diagrama/new.jpg"
    )
    access_checker = MockProjectAccessChecker(can_edit=True)

    use_case = UpdateProjectThumbnailUseCase(
        project_repository=repo,
        image_storage_provider=storage,
        access_checker=access_checker,
    )

    image_bytes = b"new-fake-jpeg-bytes"
    result = await use_case.execute(
        project_id=project_id,
        user_id=owner_id,
        image_data=image_bytes,
    )

    assert result["updated"] is True
    assert result["thumbnail_url"] == "https://res.cloudinary.com/demo/image/upload/diagrama/new.jpg"
    assert result["thumbnail_updated_at"] > old_time
    assert storage.upload_called_count == 1
    assert repo.save_called is True


async def test_thumbnail_upload_for_non_existent_project_raises_exception():
    repo = MockProjectRepository(None)
    storage = MockProjectImageStorageProvider()
    access_checker = MockProjectAccessChecker(can_edit=True)

    use_case = UpdateProjectThumbnailUseCase(
        project_repository=repo,
        image_storage_provider=storage,
        access_checker=access_checker,
    )

    with pytest.raises(ProjectNotFoundException):
        await use_case.execute(
            project_id=uuid4(),
            user_id="user-123",
            image_data=b"data",
        )


async def test_thumbnail_upload_skipped_when_project_has_no_classes():
    project_id = uuid4()
    owner_id = "user-123"
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="Proyecto Vacío",
        thumbnail_url=None,
        thumbnail_updated_at=None,
    )
    repo = MockProjectRepository(project)
    storage = MockProjectImageStorageProvider()
    access_checker = MockProjectAccessChecker(can_edit=True)
    empty_class_repo = MockDiagramClassRepository(class_count=0)

    use_case = UpdateProjectThumbnailUseCase(
        project_repository=repo,
        image_storage_provider=storage,
        access_checker=access_checker,
        diagram_class_repository=empty_class_repo,
    )

    result = await use_case.execute(
        project_id=project_id,
        user_id=owner_id,
        image_data=b"fake-image-bytes",
    )

    # No debe subir la imagen a Cloudinary ni guardar cambios si no hay clases
    assert result["updated"] is False
    assert storage.upload_called_count == 0
    assert repo.save_called is False
