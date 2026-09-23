from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.dto_generator import DtoGenerator
from app.modules.code_generation.application.services.generators.exception_handler_generator import ExceptionHandlerGenerator
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import SpringBootProjectConfig
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
)


@pytest.fixture
def config():
    return SpringBootProjectConfig(
        project_name="Shop Test",
        artifact_id="shop-backend",
        group_id="app",
        package_name="app.shop",
        database_name="shop_db",
    )


def test_dto_generator_creates_message_response(config):
    dto_gen = DtoGenerator(config)
    file = dto_gen.generate_message_response()
    assert file.relative_path == "src/main/java/app/shop/dto/MessageResponse.java"
    assert "public class MessageResponse" in file.content
    assert "private String message;" in file.content
    assert "public String getMessage()" in file.content
    assert "public void setMessage(String message)" in file.content


def test_dto_generator_request_includes_mobile_uuid_and_relations(config):
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
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="precio",
                data_type="DECIMAL",
                position=2,
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

    dto_gen = DtoGenerator(config)
    classes_map = {cat_id: cat_class, prod_id: prod_class}
    req_file = dto_gen.generate_request(prod_class, classes_map, [relation])

    assert "private UUID id;" in req_file.content
    assert "public UUID getId()" in req_file.content
    assert "private UUID categoriaId;" in req_file.content
    assert "public UUID getCategoriaId()" in req_file.content


def test_exception_handler_generator_creates_conversational_advice(config):
    eh_gen = ExceptionHandlerGenerator(config)
    file = eh_gen.generate()
    assert file.relative_path == "src/main/java/app/shop/exception/GlobalExceptionHandler.java"
    assert "@RestControllerAdvice" in file.content
    assert "ResponseStatusException.class" in file.content
    assert "DataIntegrityViolationException.class" in file.content
    assert "No se pudo completar la operación porque los datos relacionados no son válidos" in file.content
    assert "foreign key" not in file.content.lower()
    assert "primary key" not in file.content.lower()
