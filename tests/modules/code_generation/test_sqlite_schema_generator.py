import sqlite3
from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.sqlite_schema_generator import (
    SqliteSchemaGenerator,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationBridgeSnapshotDto,
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
def complex_domain_model():
    cat_id = uuid4()
    prod_id = uuid4()
    venta_id = uuid4()
    vp_id = uuid4()

    cat = DiagramClassSnapshotDto(
        id=cat_id,
        name="Categoria",
        position_x=0.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="nombre", data_type="VARCHAR", position=1, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    prod = DiagramClassSnapshotDto(
        id=prod_id,
        name="Producto",
        position_x=100.0,
        position_y=100.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="nombre", data_type="VARCHAR", position=1, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="precio", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="stock", data_type="INTEGER", position=3, is_primary_key=False, is_nullable=True
            ),
        ],
    )

    venta = DiagramClassSnapshotDto(
        id=venta_id,
        name="Venta",
        position_x=200.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="fecha", data_type="DATETIME", position=1, is_primary_key=False, is_nullable=True
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="total", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    vp = DiagramClassSnapshotDto(
        id=vp_id,
        name="VentaProducto",
        position_x=200.0,
        position_y=100.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="cantidad", data_type="DECIMAL", position=1, is_primary_key=False, is_nullable=False
            ),
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="subtotal", data_type="DECIMAL", position=2, is_primary_key=False, is_nullable=False
            ),
        ],
    )

    # 1:N Categoria -> Producto
    r1 = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="cat_prod",
        relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=cat_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="1",
        target_cardinality="0..*",
        bridge=None,
    )

    # N:M Venta <-> Producto a través de VentaProducto
    r2 = DiagramRelationSnapshotDto(
        id=uuid4(),
        name="venta_prod",
        relation_type="MANY_TO_MANY",
        source=DiagramRelationEndpointSnapshotDto(class_id=venta_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="*",
        target_cardinality="*",
        bridge=DiagramRelationBridgeSnapshotDto(class_id=vp_id, handle="center"),
    )

    return [prod, vp, cat, venta], [r1, r2]


def test_sqlite_schema_generator_generates_valid_ddl(config, complex_domain_model):
    classes, relations = complex_domain_model
    gen = SqliteSchemaGenerator(config)
    file = gen.generate(classes, relations)

    assert file.relative_path == "schema.sql"
    content = file.content

    # 1. Pragma foreign_keys
    assert "PRAGMA foreign_keys = ON;" in content

    # 2. Sentencias CREATE TABLE IF NOT EXISTS
    assert "CREATE TABLE IF NOT EXISTS categoria" in content
    assert "CREATE TABLE IF NOT EXISTS producto" in content
    assert "CREATE TABLE IF NOT EXISTS venta" in content
    assert "CREATE TABLE IF NOT EXISTS venta_producto" in content

    # 3. Claves primarias
    assert "id TEXT PRIMARY KEY NOT NULL" in content

    # 4. Tipos SQLite
    assert "nombre TEXT NOT NULL" in content
    assert "precio REAL NOT NULL" in content
    assert "stock INTEGER DEFAULT 0" in content

    # 5. Claves foráneas e índices
    assert "FOREIGN KEY (categoria_id) REFERENCES categoria(id) ON UPDATE CASCADE ON DELETE RESTRICT" in content
    assert "CREATE INDEX IF NOT EXISTS idx_producto_categoria_id ON producto(categoria_id);" in content

    # N:M Bridge: venta_producto tiene ambas FKs
    assert "FOREIGN KEY (venta_id) REFERENCES venta(id) ON UPDATE CASCADE ON DELETE RESTRICT" in content
    assert "FOREIGN KEY (producto_id) REFERENCES producto(id) ON UPDATE CASCADE ON DELETE RESTRICT" in content
    assert "CREATE INDEX IF NOT EXISTS idx_venta_producto_venta_id ON venta_producto(venta_id);" in content
    assert "CREATE INDEX IF NOT EXISTS idx_venta_producto_producto_id ON venta_producto(producto_id);" in content

    # 6. Orden topológico en el script:
    # Categoria debe aparecer antes de Producto
    cat_pos = content.index("CREATE TABLE IF NOT EXISTS categoria")
    prod_pos = content.index("CREATE TABLE IF NOT EXISTS producto")
    assert cat_pos < prod_pos

    # Venta y Producto deben aparecer antes de VentaProducto
    venta_pos = content.index("CREATE TABLE IF NOT EXISTS venta")
    vp_pos = content.index("CREATE TABLE IF NOT EXISTS venta_producto")
    assert venta_pos < vp_pos
    assert prod_pos < vp_pos


def test_sqlite_ddl_executes_in_sqlite_engine(config, complex_domain_model):
    classes, relations = complex_domain_model
    gen = SqliteSchemaGenerator(config)
    file = gen.generate(classes, relations)

    # Probar ejecución real en SQLite 3 en memoria
    conn = sqlite3.connect(":memory:")
    conn.executescript(file.content)

    # Verificar que las 4 tablas existen
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"categoria", "producto", "venta", "venta_producto"}.issubset(tables)

    # Verificar índices creados
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indices = {row[0] for row in cursor.fetchall()}
    assert "idx_producto_categoria_id" in indices
    assert "idx_venta_producto_venta_id" in indices
    assert "idx_venta_producto_producto_id" in indices

    # Verificar inserción respetando integridad referencial
    cursor.execute("INSERT INTO categoria (id, nombre) VALUES ('cat-1', 'Bebidas');")
    cursor.execute("INSERT INTO producto (id, nombre, precio, stock, categoria_id) VALUES ('prod-1', 'Agua', 1.5, 100, 'cat-1');")
    cursor.execute("INSERT INTO venta (id, fecha, total) VALUES ('ven-1', '2026-09-18', 1.5);")
    cursor.execute("INSERT INTO venta_producto (id, venta_id, producto_id, cantidad, subtotal) VALUES ('vp-1', 'ven-1', 'prod-1', 1.0, 1.5);")
    conn.commit()

    # Comprobar que foreign_key_check no tiene violaciones
    cursor.execute("PRAGMA foreign_key_check;")
    violations = cursor.fetchall()
    assert len(violations) == 0

    # Comprobar que viola FK si se intenta insertar con id inexistente
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("INSERT INTO producto (id, nombre, precio, categoria_id) VALUES ('prod-2', 'Refresco', 2.0, 'cat-inexistente');")
        conn.commit()

    conn.close()
