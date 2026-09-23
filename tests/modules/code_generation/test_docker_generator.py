from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.docker_generator import (
    DockerAndConfigGenerator,
)
from app.modules.code_generation.application.services.generators.spring_boot_generator import (
    SpringBootGenerator,
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
        project_name="Inventory App",
        artifact_id="inventory-backend",
        group_id="app",
        package_name="app.inventory",
        database_name="inventory_db",
        server_port=8080,
    )


@pytest.fixture
def sample_model():
    cat_id = uuid4()
    prod_id = uuid4()

    category = DiagramClassSnapshotDto(
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

    producto = DiagramClassSnapshotDto(
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

    return [category, producto], [relation]


def test_api_reference_generation_content(config, sample_model):
    classes, relations = sample_model
    gen = DockerAndConfigGenerator(config)
    api_ref_file = gen.generate_api_reference(classes, relations)

    assert api_ref_file.relative_path == "API_REFERENCE.md"
    content = api_ref_file.content

    # Key architecture conventions explained
    assert "JpaRepository" in content
    assert "capabilities.json" in content
    assert "Identidad Mobile-First" in content
    assert '{"message": "..."}' in content

    # Entity documentation present
    assert "### Entidad: `Producto`" in content
    assert "### Entidad: `Categoria`" in content
    assert "POST /api/productos" in content
    assert "PUT /api/productos/{id}" in content
    assert "DELETE /api/productos/{id}" in content
    assert "GET /api/productos" in content
    assert "GET /api/productos/{id}" in content

    # Conversational relation error messages
    assert "Categoria obligatoria" in content
    assert "Categoria no encontrada" in content
    assert "Producto registrado correctamente" in content


def test_docker_generator_generate_all_includes_api_reference(config, sample_model):
    classes, relations = sample_model
    gen = DockerAndConfigGenerator(config)
    files = gen.generate_all(classes, relations)

    file_paths = [f.relative_path for f in files]
    assert "API_REFERENCE.md" in file_paths
    assert "pom.xml" in file_paths
    assert "Dockerfile" in file_paths
    assert "docker-compose.yml" in file_paths
    assert "README.md" in file_paths


def test_spring_boot_generator_includes_api_reference_in_zip(config, sample_model):
    import io
    import zipfile

    classes, relations = sample_model
    generator = SpringBootGenerator(config)
    archive = generator.generate(classes, relations)

    with zipfile.ZipFile(io.BytesIO(archive.zip_bytes)) as z:
        names = z.namelist()
        assert any(n.endswith("API_REFERENCE.md") for n in names)
        assert any(n.endswith("capabilities.json") for n in names)
