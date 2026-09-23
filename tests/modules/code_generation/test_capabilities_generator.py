import json
from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.capabilities_generator import (
    CapabilitiesGenerator,
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
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="stock",
                data_type="INTEGER",
                position=3,
                is_primary_key=False,
                is_nullable=True,
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


def test_capabilities_generator_produces_compact_v2(config, sample_model):
    classes, relations = sample_model
    gen = CapabilitiesGenerator(config)
    file = gen.generate(classes, relations)

    assert file.relative_path == "capabilities.json"
    data = json.loads(file.content)

    # 1. Global config
    assert data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert data["project_name"] == "Inventory App"
    assert data["version"] == "2.0.0"
    assert data["base_url"] == "http://localhost:8080"
    assert data["api_prefix"] == "/api"
    assert data["standard_crud"] == {
        "enabled": True,
        "operations": ["CREATE", "READ_ALL", "READ_BY_ID", "UPDATE", "DELETE"],
        "response_envelope": "message",
    }
    assert "entities" in data

    # 2. Assert NO redundant actions / verbose blocks exist
    assert "actions" not in data
    assert "ai_agent_instructions" not in data

    # 3. Check entities
    entities_by_name = {e["name"]: e for e in data["entities"]}
    assert "Categoria" in entities_by_name
    assert "Producto" in entities_by_name

    # Categoria
    cat_entity = entities_by_name["Categoria"]
    assert cat_entity["table_name"] == "categoria"
    assert cat_entity["endpoint"] == "/categorias"
    assert cat_entity["relationships"] == []
    cat_fields = {f["name"]: f for f in cat_entity["fields"]}
    assert cat_fields["id"]["type"] == "UUID"
    assert cat_fields["id"]["primary_key"] is True
    assert cat_fields["id"]["required"] is True
    assert cat_fields["nombre"]["type"] == "STRING"
    assert cat_fields["nombre"]["required"] is True

    # Producto
    prod_entity = entities_by_name["Producto"]
    assert prod_entity["table_name"] == "producto"
    assert prod_entity["endpoint"] == "/productos"
    prod_fields = {f["name"]: f for f in prod_entity["fields"]}
    assert prod_fields["id"]["type"] == "UUID"
    assert prod_fields["nombre"]["type"] == "STRING"
    assert prod_fields["precio"]["type"] == "DECIMAL"
    assert prod_fields["stock"]["type"] == "INTEGER"
    assert prod_fields["stock"]["required"] is False
    assert prod_fields["stock"]["default"] == 0
    # FK field added
    assert "categoriaId" in prod_fields
    assert prod_fields["categoriaId"]["type"] == "UUID"
    assert prod_fields["categoriaId"]["required"] is True

    # Relationships
    assert len(prod_entity["relationships"]) == 1
    rel = prod_entity["relationships"][0]
    assert rel["field_name"] == "categoriaId"
    assert rel["target_entity"] == "Categoria"
    assert rel["target_table"] == "categoria"
    assert rel["type"] == "ManyToOne"
    assert rel["required"] is True

    # 4. Size requirement (< 5 KB)
    assert len(file.content.encode("utf-8")) < 5120


def test_capabilities_many_to_many_bridge(config):
    cat_id = uuid4()
    prod_id = uuid4()
    venta_id = uuid4()
    vp_id = uuid4()

    cat = DiagramClassSnapshotDto(
        id=cat_id, name="Categoria", position_x=0.0, position_y=0.0,
        attributes=[DiagramAttributeSnapshotDto(id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)]
    )
    prod = DiagramClassSnapshotDto(
        id=prod_id, name="Producto", position_x=0.0, position_y=0.0,
        attributes=[DiagramAttributeSnapshotDto(id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)]
    )
    venta = DiagramClassSnapshotDto(
        id=venta_id, name="Venta", position_x=0.0, position_y=0.0,
        attributes=[DiagramAttributeSnapshotDto(id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False)]
    )
    vp = DiagramClassSnapshotDto(
        id=vp_id, name="VentaProducto", position_x=0.0, position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(id=uuid4(), name="id", data_type="UUID", position=0, is_primary_key=True, is_nullable=False),
            DiagramAttributeSnapshotDto(id=uuid4(), name="cantidad", data_type="DECIMAL", position=1, is_primary_key=False, is_nullable=False),
        ]
    )

    # Relación 1:N Categoria -> Producto
    r1 = DiagramRelationSnapshotDto(
        id=uuid4(), name="cat_prod", relation_type="ASSOCIATION",
        source=DiagramRelationEndpointSnapshotDto(class_id=cat_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="1", target_cardinality="0..*", bridge=None
    )
    # Relación N:M Venta <-> Producto con bridge VentaProducto
    r2 = DiagramRelationSnapshotDto(
        id=uuid4(), name="venta_prod", relation_type="MANY_TO_MANY",
        source=DiagramRelationEndpointSnapshotDto(class_id=venta_id, handle="bottom"),
        target=DiagramRelationEndpointSnapshotDto(class_id=prod_id, handle="top"),
        source_cardinality="*", target_cardinality="*",
        bridge=DiagramRelationBridgeSnapshotDto(class_id=vp_id, handle="center")
    )

    gen = CapabilitiesGenerator(config)
    file = gen.generate([cat, prod, venta, vp], [r1, r2])
    data = json.loads(file.content)
    entities = {e["name"]: e for e in data["entities"]}

    # Producto solo tiene categoriaId, NO ventaId
    prod_fields = {f["name"] for f in entities["Producto"]["fields"]}
    assert "categoriaId" in prod_fields
    assert "ventaId" not in prod_fields

    # Venta NO tiene productoId
    venta_fields = {f["name"] for f in entities["Venta"]["fields"]}
    assert "productoId" not in venta_fields

    # VentaProducto tiene ambos
    vp_fields = {f["name"] for f in entities["VentaProducto"]["fields"]}
    assert "ventaId" in vp_fields
    assert "productoId" in vp_fields
    assert "cantidad" in vp_fields

    vp_rels = {r["field_name"]: r for r in entities["VentaProducto"]["relationships"]}
    assert "ventaId" in vp_rels
    assert "productoId" in vp_rels
    assert vp_rels["ventaId"]["target_entity"] == "Venta"
    assert vp_rels["productoId"]["target_entity"] == "Producto"
