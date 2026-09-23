from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.entity_generator import (
    EntityGenerator,
)
from app.modules.code_generation.application.services.generators.service_generator import (
    ServiceGenerator,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
)


@pytest.fixture
def config():
    return SpringBootProjectConfig(
        project_name="UUID Test",
        artifact_id="uuid-backend",
        group_id="app",
        package_name="app.uuid_test",
        database_name="uuid_db",
    )


@pytest.fixture
def class_with_uuid():
    c_id = uuid4()
    return DiagramClassSnapshotDto(
        id=c_id,
        name="Cliente",
        position_x=0.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="nombre",
                data_type="TEXT",
                position=1,
                is_primary_key=False,
                is_nullable=False,
            ),
        ],
    )


def test_entity_generator_does_not_force_generated_value_for_uuid(config, class_with_uuid):
    gen = EntityGenerator(config)
    file = gen.generate(class_with_uuid, {class_with_uuid.id: class_with_uuid}, [])

    assert "@Id" in file.content
    assert 'GenerationType.UUID' not in file.content
    assert '@Column(name = "id", nullable = false, updatable = false)' in file.content


def test_service_generator_assigns_client_or_fallback_uuid(config, class_with_uuid):
    service_gen = ServiceGenerator(config)
    file = service_gen.generate(class_with_uuid, {class_with_uuid.id: class_with_uuid}, [])

    assert "if (request.getId() != null)" in file.content
    assert "entity.setId(request.getId());" in file.content
    assert "entity.setId(UUID.randomUUID());" in file.content
