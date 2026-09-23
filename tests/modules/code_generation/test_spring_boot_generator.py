import io
import zipfile
from uuid import UUID, uuid4
import pytest

from app.modules.code_generation.application.services.generators.entity_generator import (
    EntityGenerator,
)
from app.modules.code_generation.application.services.generators.repository_generator import (
    RepositoryGenerator,
)
from app.modules.code_generation.application.services.generators.service_generator import (
    ServiceGenerator,
)
from app.modules.code_generation.application.services.generators.controller_generator import (
    ControllerGenerator,
)
from app.modules.code_generation.application.services.generators.docker_generator import (
    DockerAndConfigGenerator,
)
from app.modules.code_generation.application.services.generators.spring_boot_generator import (
    SpringBootGenerator,
)
from app.modules.code_generation.domain.exceptions import EmptyDiagramException
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
def sample_config():
    return SpringBootProjectConfig(
        project_name="E-Commerce App",
        artifact_id="ecommerce-backend",
        group_id="com.ecommerce",
        package_name="com.ecommerce.backend",
        database_name="ecommerce_db",
    )


@pytest.fixture
def sample_classes():
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
                data_type="INTEGER",
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
                data_type="INTEGER",
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
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="stock",
                data_type="INTEGER",
                position=3,
                is_primary_key=False,
                is_nullable=False,
            ),
        ],
    )

    return [category, producto]


@pytest.fixture
def sample_relations(sample_classes):
    cat = sample_classes[0]
    prod = sample_classes[1]
    rel = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="pertenece_a",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=cat.id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod.id, handle="top"),
        source_cardinality="1",
        target_cardinality="0..*",
        bridge=None,
    )
    return [rel]


def test_entity_generator(sample_config, sample_classes, sample_relations):
    gen = EntityGenerator(sample_config)
    classes_map = {c.id: c for c in sample_classes}

    file = gen.generate(sample_classes[1], classes_map, sample_relations)
    assert file.relative_path == "src/main/java/com/ecommerce/backend/model/Producto.java"
    content = str(file.content)
    assert "@Entity" in content
    assert '@Table(name = "productos")' in content or '@Table(name = "producto")' in content
    assert "private Integer id;" in content
    assert "private String nombre;" in content
    assert "private Double precio;" in content
    assert "private Integer stock;" in content
    assert "@ManyToOne" in content
    assert "private Categoria categoria;" in content
    assert "public String getNombre()" in content
    assert "public void setNombre(String nombre)" in content


def test_repository_generator(sample_config, sample_classes):
    gen = RepositoryGenerator(sample_config)
    file = gen.generate(sample_classes[0])
    assert file.relative_path == "src/main/java/com/ecommerce/backend/repository/CategoriaRepository.java"
    content = str(file.content)
    assert "@Repository" in content
    assert "public interface CategoriaRepository extends JpaRepository<Categoria, Integer>" in content


def test_service_generator(sample_config, sample_classes):
    gen = ServiceGenerator(sample_config)
    file = gen.generate(sample_classes[1])
    assert file.relative_path == "src/main/java/com/ecommerce/backend/service/ProductoService.java"
    content = str(file.content)
    assert "@Service" in content
    assert "public List<ProductoResponse> findAll()" in content
    assert "public ProductoResponse findById(Integer id)" in content
    assert "public ProductoResponse create(ProductoRequest request)" in content
    assert "public ProductoResponse update(Integer id, ProductoRequest request)" in content
    assert "public void deleteById(Integer id)" in content


def test_controller_generator(sample_config, sample_classes):
    gen = ControllerGenerator(sample_config)
    file = gen.generate(sample_classes[1])
    assert file.relative_path == "src/main/java/com/ecommerce/backend/controller/ProductoController.java"
    content = str(file.content)
    assert "@RestController" in content
    assert '@RequestMapping("/api/productos")' in content
    assert "public List<ProductoResponse> getAll()" in content
    assert "public MessageResponse create(@Valid @RequestBody ProductoRequest request)" in content
    assert 'public MessageResponse update(@PathVariable("id") Integer id, @Valid @RequestBody ProductoRequest request)' in content
    assert 'public MessageResponse delete(@PathVariable("id") Integer id)' in content


def test_docker_generator(sample_config, sample_classes):
    gen = DockerAndConfigGenerator(sample_config)
    files = gen.generate_all(sample_classes)
    rel_paths = {f.relative_path for f in files}

    assert "pom.xml" in rel_paths
    assert "src/main/resources/application.properties" in rel_paths
    assert "src/main/java/com/ecommerce/backend/Application.java" in rel_paths
    assert "Dockerfile" in rel_paths
    assert "docker-compose.yml" in rel_paths
    assert ".dockerignore" in rel_paths
    assert "README.md" in rel_paths

    readme = next(f for f in files if f.relative_path == "README.md")
    assert "docker compose up --build" in str(readme.content)
    assert "/api/productos" in str(readme.content)


def test_spring_boot_generator_zip(sample_config, sample_classes, sample_relations):
    coordinator = SpringBootGenerator(sample_config)
    archive = coordinator.generate(sample_classes, sample_relations)

    assert archive.filename == "backend-e-commerce-app.zip"
    assert archive.total_files > 0
    assert len(archive.zip_bytes) > 0

    # Verificar que el ZIP es legible y contiene los archivos esperados
    with zipfile.ZipFile(io.BytesIO(archive.zip_bytes)) as z:
        names = z.namelist()
        assert "backend-e-commerce-app/pom.xml" in names
        assert "backend-e-commerce-app/Dockerfile" in names
        assert "backend-e-commerce-app/docker-compose.yml" in names
        assert "backend-e-commerce-app/src/main/java/com/ecommerce/backend/model/Producto.java" in names
        assert "backend-e-commerce-app/src/main/java/com/ecommerce/backend/controller/ProductoController.java" in names


def test_empty_diagram_raises_exception(sample_config):
    coordinator = SpringBootGenerator(sample_config)
    with pytest.raises(EmptyDiagramException):
        coordinator.generate([], [])


def test_duplicate_and_secondary_id_attributes_sanitized(sample_config):
    """Verifica que atributos secundarios como 'Id' o nombres duplicados se saniticen sin colisión."""
    class_with_duplicate_id = DiagramClassSnapshotDto(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="Employee",
        position_x=0.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=UUID("11111111-1111-1111-1111-111111111111"),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
                is_foreign_key=False,
            ),
            DiagramAttributeSnapshotDto(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                name="Name",
                data_type="TEXT",
                position=1,
                is_primary_key=False,
                is_nullable=True,
                is_foreign_key=False,
            ),
            DiagramAttributeSnapshotDto(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                name="Id",
                data_type="INTEGER",
                position=2,
                is_primary_key=False,
                is_nullable=True,
                is_foreign_key=False,
            ),
        ],
    )

    coordinator = SpringBootGenerator(sample_config)
    archive = coordinator.generate([class_with_duplicate_id], [])

    with zipfile.ZipFile(io.BytesIO(archive.zip_bytes)) as z:
        entity_content = z.read("backend-e-commerce-app/src/main/java/com/ecommerce/backend/model/Employee.java").decode("utf-8")
        assert "private UUID id;" in entity_content
        assert "private Integer externalId;" in entity_content
        assert "public UUID getId()" in entity_content
        assert "public Integer getExternalId()" in entity_content

        dto_content = z.read("backend-e-commerce-app/src/main/java/com/ecommerce/backend/dto/EmployeeResponse.java").decode("utf-8")
        assert "private UUID id;" in dto_content
        assert "private Integer externalId;" in dto_content

        svc_content = z.read("backend-e-commerce-app/src/main/java/com/ecommerce/backend/service/EmployeeService.java").decode("utf-8")
        assert "response.setExternalId(entity.getExternalId());" in svc_content



def test_clean_package_structure_and_no_generic_sample_folders(sample_classes):
    clean_config = SpringBootProjectConfig(
        project_name="Hotel System",
        artifact_id="hotel-system-backend",
        group_id="app",
        package_name="app.hotel_system",
        database_name="hotel_system_db",
    )

    coordinator = SpringBootGenerator(clean_config)
    archive = coordinator.generate(sample_classes, [])

    with zipfile.ZipFile(io.BytesIO(archive.zip_bytes)) as z:
        names = z.namelist()
        # Verify app/hotel_system exists
        assert any("src/main/java/app/hotel_system/Application.java" in name for name in names)
        assert any("src/main/java/app/hotel_system/exception/GlobalExceptionHandler.java" in name for name in names)
        assert any("src/main/java/app/hotel_system/dto/MessageResponse.java" in name for name in names)
        assert any("capabilities.json" in name for name in names)
        assert any("schema.sql" in name for name in names)

        # Verify NO com/example or sample in paths
        for name in names:
            assert "com/example" not in name
            assert "sample" not in name.lower() or name.endswith("Application.java") or "hotel_system" in name


def test_generate_backend_with_many_to_many_and_one_to_many_relations():
    cat_id = uuid4()
    prod_id = uuid4()
    venta_id = uuid4()
    compra_id = uuid4()
    vp_id = uuid4()
    cp_id = uuid4()

    categoria = DiagramClassSnapshotDto(
        id=cat_id,
        name="Categoria",
        position_x=0.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="nombre", data_type="TEXT", position=1, is_primary_key=False, is_nullable=False
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
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="nombre", data_type="TEXT", position=1, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="precio", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="stock", data_type="INTEGER", position=3, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="categoria_id",
                data_type="UUID",
                position=4,
                is_primary_key=False,
                is_nullable=False,
                is_foreign_key=True,
                referenced_class_id=cat_id,
            ),
        ],
    )

    venta = DiagramClassSnapshotDto(
        id=venta_id,
        name="Venta",
        position_x=300.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="fecha_venta", data_type="DATE", position=1, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="total", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    compra = DiagramClassSnapshotDto(
        id=compra_id,
        name="Compra",
        position_x=300.0,
        position_y=200.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="fecha_compra", data_type="DATE", position=1, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="total", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    venta_producto = DiagramClassSnapshotDto(
        id=vp_id,
        name="VentaProducto",
        position_x=200.0,
        position_y=50.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="venta_id",
                data_type="UUID",
                position=1,
                is_primary_key=False,
                is_nullable=False,
                is_foreign_key=True,
                referenced_class_id=venta_id,
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="producto_id",
                data_type="UUID",
                position=2,
                is_primary_key=False,
                is_nullable=False,
                is_foreign_key=True,
                referenced_class_id=prod_id,
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="cantidad", data_type="INTEGER", position=3, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="subtotal", data_type="DECIMAL", position=4, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    compra_producto = DiagramClassSnapshotDto(
        id=cp_id,
        name="CompraProducto",
        position_x=200.0,
        position_y=150.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="compra_id",
                data_type="UUID",
                position=1,
                is_primary_key=False,
                is_nullable=False,
                is_foreign_key=True,
                referenced_class_id=compra_id,
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="producto_id",
                data_type="UUID",
                position=2,
                is_primary_key=False,
                is_nullable=False,
                is_foreign_key=True,
                referenced_class_id=prod_id,
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="cantidad", data_type="INTEGER", position=3, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="precio_unitario", data_type="DECIMAL", position=4, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
        DiagramRelationBridgeSnapshotDto,
    )

    # Relación 1:N Categoria -> Producto
    rel_cat_prod = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="pertenece_a",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=cat_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="1",
        target_cardinality="0..*",
        bridge=None,
    )

    # Relación N:M Venta <-> Producto con puente VentaProducto
    rel_venta_prod = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="VentasProductos",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=venta_id, handle="right"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="left"),
        source_cardinality="0..*",
        target_cardinality="0..*",
        bridge=DiagramRelationBridgeSnapshotDto(class_id=vp_id, handle="top"),
    )

    # Relación N:M Compra <-> Producto con puente CompraProducto
    rel_compra_prod = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="ComprasProductos",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=compra_id, handle="right"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="left"),
        source_cardinality="0..*",
        target_cardinality="0..*",
        bridge=DiagramRelationBridgeSnapshotDto(class_id=cp_id, handle="top"),
    )

    classes_list = [categoria, producto, venta, compra, venta_producto, compra_producto]
    relations_list = [rel_cat_prod, rel_venta_prod, rel_compra_prod]

    config = SpringBootProjectConfig(
        project_name="Shop App",
        artifact_id="shop-backend",
        group_id="app",
        package_name="app.shop",
        database_name="shop_db",
    )

    generator = SpringBootGenerator(config)
    archive = generator.generate(classes_list, relations_list)

    with zipfile.ZipFile(io.BytesIO(archive.zip_bytes)) as z:
        # 1. ProductoRequest debe tener categoriaId, pero NO ventaId ni compraId
        prod_req = z.read("backend-shop-app/src/main/java/app/shop/dto/ProductoRequest.java").decode("utf-8")
        assert "private UUID categoriaId;" in prod_req
        assert "ventaId" not in prod_req
        assert "compraId" not in prod_req

        # 2. ProductoService debe inyectar CategoriaRepository, pero NO VentaRepository ni CompraRepository
        prod_svc = z.read("backend-shop-app/src/main/java/app/shop/service/ProductoService.java").decode("utf-8")
        assert "CategoriaRepository" in prod_svc
        assert "VentaRepository" not in prod_svc
        assert "CompraRepository" not in prod_svc
        assert "Categoria obligatoria" in prod_svc
        assert "Venta obligatoria" not in prod_svc
        assert "Compra obligatoria" not in prod_svc

        # 3. ProductoEntity debe tener @ManyToOne de Categoria, pero NO de Venta ni Compra
        prod_entity = z.read("backend-shop-app/src/main/java/app/shop/model/Producto.java").decode("utf-8")
        assert "private Categoria categoria;" in prod_entity
        assert "private Venta venta;" not in prod_entity
        assert "private Compra compra;" not in prod_entity

        # 4. Las clases puente SI deben tener sus llaves foráneas
        vp_req = z.read("backend-shop-app/src/main/java/app/shop/dto/VentaProductoRequest.java").decode("utf-8")
        assert "ventaId" in vp_req
        assert "productoId" in vp_req

        cp_req = z.read("backend-shop-app/src/main/java/app/shop/dto/CompraProductoRequest.java").decode("utf-8")
        assert "compraId" in cp_req
        assert "productoId" in cp_req

        # 5. capabilities.json v2 debe reflejar la estructura correcta
        import json
        cap_content = json.loads(z.read("backend-shop-app/capabilities.json").decode("utf-8"))
        assert cap_content["version"] == "2.0.0"
        entities_by_name = {e["name"]: e for e in cap_content["entities"]}
        prod_fields = {f["name"] for f in entities_by_name["Producto"]["fields"]}
        assert "categoriaId" in prod_fields
        assert "ventaId" not in prod_fields
        assert "compraId" not in prod_fields

        # 6. schema.sql debe existir y contener las sentencias DDL SQLite
        schema_sql = z.read("backend-shop-app/schema.sql").decode("utf-8")
        assert "PRAGMA foreign_keys = ON;" in schema_sql
        assert "CREATE TABLE IF NOT EXISTS producto" in schema_sql
        assert "CREATE TABLE IF NOT EXISTS venta_producto" in schema_sql
        assert "FOREIGN KEY (categoria_id) REFERENCES categoria(id)" in schema_sql
