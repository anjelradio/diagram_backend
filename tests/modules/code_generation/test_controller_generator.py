from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.controller_generator import (
    ControllerGenerator,
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
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
)


@pytest.fixture
def config():
    return SpringBootProjectConfig(
        project_name="Test Store",
        artifact_id="test-store-backend",
        group_id="app",
        package_name="app.test_store",
        database_name="test_store_db",
    )


@pytest.fixture
def product_and_category_classes():
    cat_id = uuid4()
    prod_id = uuid4()

    cat_class = DiagramClassSnapshotDto(
        id=cat_id,
        name="Categoria",
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

    prod_class = DiagramClassSnapshotDto(
        id=prod_id,
        name="Producto",
        position_x=100.0,
        position_y=100.0,
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

    relation = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="pertenece_a",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=cat_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="1",
        target_cardinality="0..*",
        bridge=None,
    )

    return cat_class, prod_class, relation


def test_controller_generator_returns_message_response(config, product_and_category_classes):
    _, prod_class, _ = product_and_category_classes
    controller_gen = ControllerGenerator(config)
    file = controller_gen.generate(prod_class)

    assert "public MessageResponse create(" in file.content
    assert 'return new MessageResponse("Producto registrado correctamente");' in file.content
    assert "public MessageResponse update(" in file.content
    assert 'return new MessageResponse("Producto actualizado correctamente");' in file.content
    assert "public MessageResponse delete(" in file.content
    assert 'return new MessageResponse("Producto eliminado correctamente");' in file.content


def test_service_generator_validates_relationships_with_conversational_messages(config, product_and_category_classes):
    cat_class, prod_class, relation = product_and_category_classes
    service_gen = ServiceGenerator(config)

    classes_map = {cat_class.id: cat_class, prod_class.id: prod_class}
    file = service_gen.generate(prod_class, classes_map, [relation])

    assert "private final CategoriaRepository categoriaRepository;" in file.content
    assert 'throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Categoria obligatoria");' in file.content
    assert 'new ResponseStatusException(HttpStatus.BAD_REQUEST, "Categoria no encontrada")' in file.content
    assert "foreign key" not in file.content.lower()
