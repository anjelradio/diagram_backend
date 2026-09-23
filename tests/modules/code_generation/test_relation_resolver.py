from uuid import uuid4
import pytest

from app.modules.code_generation.application.services.generators.relation_resolver import (
    is_many_to_many_relation,
    resolve_entity_dependencies,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationBridgeSnapshotDto,
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
)


@pytest.fixture
def user_domain_model():
    """
    Modelo del usuario:
    - Categoria
    - Producto (con FK a Categoria)
    - Venta
    - Compra
    - VentaProducto (puente N:M entre Venta y Producto)
    - CompraProducto (puente N:M entre Compra y Producto)
    """
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
    all_classes_map = {c.id: c for c in classes_list}

    return all_classes_map, relations_list, {
        "cat_id": cat_id,
        "prod_id": prod_id,
        "venta_id": venta_id,
        "compra_id": compra_id,
        "vp_id": vp_id,
        "cp_id": cp_id,
    }


def test_is_many_to_many_detection(user_domain_model):
    all_classes_map, relations_list, ids = user_domain_model
    rel_cat_prod, rel_venta_prod, rel_compra_prod = relations_list

    assert not is_many_to_many_relation(rel_cat_prod)
    assert is_many_to_many_relation(rel_venta_prod)
    assert is_many_to_many_relation(rel_compra_prod)


def test_producto_only_depends_on_categoria(user_domain_model):
    all_classes_map, relations_list, ids = user_domain_model
    prod = all_classes_map[ids["prod_id"]]

    deps = resolve_entity_dependencies(prod, all_classes_map, relations_list)

    # CRÍTICO: Producto solo debe depender de Categoria, NUNCA de Venta ni Compra
    dep_names = [d.referenced_class_name for d in deps]
    assert "Categoria" in dep_names
    assert "Venta" not in dep_names
    assert "Compra" not in dep_names
    assert len(deps) == 1

    cat_dep = deps[0]
    assert cat_dep.referenced_class_name == "Categoria"
    assert cat_dep.fk_field_name == "categoriaId"
    assert cat_dep.repo_name == "CategoriaRepository"


def test_venta_and_compra_have_no_foreign_keys(user_domain_model):
    all_classes_map, relations_list, ids = user_domain_model
    venta = all_classes_map[ids["venta_id"]]
    compra = all_classes_map[ids["compra_id"]]

    venta_deps = resolve_entity_dependencies(venta, all_classes_map, relations_list)
    assert len(venta_deps) == 0

    compra_deps = resolve_entity_dependencies(compra, all_classes_map, relations_list)
    assert len(compra_deps) == 0


def test_bridge_classes_receive_both_foreign_keys(user_domain_model):
    all_classes_map, relations_list, ids = user_domain_model
    vp = all_classes_map[ids["vp_id"]]
    cp = all_classes_map[ids["cp_id"]]

    vp_deps = resolve_entity_dependencies(vp, all_classes_map, relations_list)
    vp_names = {d.referenced_class_name for d in vp_deps}
    assert vp_names == {"Venta", "Producto"}

    cp_deps = resolve_entity_dependencies(cp, all_classes_map, relations_list)
    cp_names = {d.referenced_class_name for d in cp_deps}
    assert cp_names == {"Compra", "Producto"}


def test_topological_sort_classes(user_domain_model):
    from app.modules.code_generation.application.services.generators.relation_resolver import (
        topological_sort_classes,
    )

    all_classes_map, relations_list, _ = user_domain_model
    # Shuffle or pass in reverse order
    classes = list(all_classes_map.values())
    classes.reverse()

    sorted_classes = topological_sort_classes(classes, relations_list)
    sorted_names = [c.name for c in sorted_classes]

    # Categoria debe preceder a Producto
    assert sorted_names.index("Categoria") < sorted_names.index("Producto")
    # Venta debe preceder a VentaProducto
    assert sorted_names.index("Venta") < sorted_names.index("VentaProducto")
    # Compra debe preceder a CompraProducto
    assert sorted_names.index("Compra") < sorted_names.index("CompraProducto")
    # Producto debe preceder a VentaProducto y CompraProducto
    assert sorted_names.index("Producto") < sorted_names.index("VentaProducto")
    assert sorted_names.index("Producto") < sorted_names.index("CompraProducto")
