import pytest
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.providers.ai_provider import AiAction
from app.modules.assistant.application.services.action_planner import (
    ActionPlanner,
)
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.exceptions import (
    AgentActionValidationException,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
    DiagramSnapshotDto,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)


def test_plan_create_class_and_attribute() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"
    snapshot = DiagramSnapshotDto(classes=[], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_CLASS,
            payload={"name": "Cliente"},
        ),
        AiAction(
            type=AgentActionType.CREATE_ATTRIBUTE,
            payload={"class_name": "Cliente", "name": "email", "data_type": "TEXT"},
        ),
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 2
    create_class_action = planned[0]
    assert create_class_action.action_type == AgentActionType.CREATE_CLASS
    assert create_class_action.payload["name"] == "Cliente"
    assert "id" in create_class_action.payload
    assert "primary_attribute_id" in create_class_action.payload

    create_attr_action = planned[1]
    assert create_attr_action.action_type == AgentActionType.CREATE_ATTRIBUTE
    assert create_attr_action.payload["class_id"] == create_class_action.payload["id"]
    assert create_attr_action.payload["name"] == "email"
    assert create_attr_action.payload["position"] == 1

    zero_position = planner.plan_actions(
        project_id,
        user_id,
        [AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "Origen", "position_x": 0, "position_y": 0})],
        snapshot,
    )[0]
    assert zero_position.payload["position_x"] == 0
    assert zero_position.payload["position_y"] == 0


def test_plan_duplicate_class_raises_error() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    existing_class = DiagramClassSnapshotDto(
        id=uuid4(),
        name="Producto",
        position_x=100.0,
        position_y=100.0,
        attributes=[],
    )
    snapshot = DiagramSnapshotDto(classes=[existing_class], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_CLASS,
            payload={"name": "Producto"},
        )
    ]

    with pytest.raises(AgentActionValidationException):
        planner.plan_actions(project_id, user_id, actions, snapshot)


def test_plan_create_relation_foreign_key() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c1_id = uuid4()
    c2_id = uuid4()
    c1 = DiagramClassSnapshotDto(
        id=c1_id,
        name="Empresa",
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
            )
        ],
    )
    c2 = DiagramClassSnapshotDto(
        id=c2_id,
        name="Empleado",
        position_x=400.0,
        position_y=100.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c1, c2], relations=[])

    # Empresa 1 -> * Empleado (FK en Empleado hacia Empresa)
    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Empresa",
                "target_class_name": "Empleado",
                "relation_type": "ASSOCIATION",
                "source_cardinality": "1",
                "target_cardinality": "0..*",
            },
        )
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 1
    rel_action = planned[0]
    assert rel_action.action_type == AgentActionType.CREATE_RELATION
    assert rel_action.payload["source_class_id"] == c1_id
    assert rel_action.payload["target_class_id"] == c2_id

    mat = rel_action.payload["materialization"]
    assert mat["strategy"] == "FOREIGN_KEY"
    assert len(mat["foreign_attributes"]) == 1
    fa = mat["foreign_attributes"][0]
    assert fa["class_id"] == str(c2_id)  # Empleado recibe la FK
    assert fa["referenced_class_id"] == str(c1_id)  # Referencia a Empresa
    assert rel_action.payload["source_handle"].value == "RIGHT_CENTER"
    assert rel_action.payload["target_handle"].value == "LEFT_CENTER"


def test_plan_create_relation_many_to_many_bridge() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c1_id = uuid4()
    c2_id = uuid4()
    c1 = DiagramClassSnapshotDto(
        id=c1_id,
        name="Estudiante",
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
            )
        ],
    )
    c2 = DiagramClassSnapshotDto(
        id=c2_id,
        name="Curso",
        position_x=400.0,
        position_y=100.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c1, c2], relations=[])

    # Estudiante * -> * Curso (N:M -> clase puente)
    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Estudiante",
                "target_class_name": "Curso",
                "relation_type": "ASSOCIATION",
                "source_cardinality": "0..*",
                "target_cardinality": "1..*",
            },
        )
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 1
    rel_action = planned[0]
    mat = rel_action.payload["materialization"]
    assert mat["strategy"] == "BRIDGE_CLASS"
    bridge = mat["bridge_class"]
    assert "EstudianteCurso" in bridge["name"]
    assert len(bridge["foreign_attributes"]) == 2


def test_plan_relation_replaces_congested_proposed_handle() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    source_id, target_id = uuid4(), uuid4()
    source = DiagramClassSnapshotDto(
        id=source_id,
        name="Origen",
        position_x=0.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0,
                is_primary_key=True, is_nullable=False,
            )
        ],
    )
    target = DiagramClassSnapshotDto(
        id=target_id,
        name="Destino",
        position_x=400.0,
        position_y=0.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(), name="id", data_type="UUID", position=0,
                is_primary_key=True, is_nullable=False,
            )
        ],
    )
    occupied = [
        DiagramRelationSnapshotDto(
            id=uuid4(), name="r1", relation_type="ASSOCIATION",
            source=DiagramRelationEndpointSnapshotDto(source_id, "RIGHT_CENTER"),
            target=DiagramRelationEndpointSnapshotDto(target_id, "LEFT_CENTER"),
            source_cardinality="1", target_cardinality="1", bridge=None,
        ),
        DiagramRelationSnapshotDto(
            id=uuid4(), name="r2", relation_type="ASSOCIATION",
            source=DiagramRelationEndpointSnapshotDto(source_id, "RIGHT_CENTER"),
            target=DiagramRelationEndpointSnapshotDto(target_id, "LEFT_CENTER"),
            source_cardinality="1", target_cardinality="1", bridge=None,
        ),
    ]
    planned = planner.plan_actions(
        project_id,
        "user_1",
        [
            AiAction(
                type=AgentActionType.CREATE_RELATION,
                payload={
                    "source_class_name": "Origen",
                    "target_class_name": "Destino",
                    "relation_type": "ASSOCIATION",
                    "source_handle": "RIGHT_CENTER",
                    "target_handle": "LEFT_CENTER",
                    "source_cardinality": "1",
                    "target_cardinality": "1",
                },
            )
        ],
        DiagramSnapshotDto(classes=[source, target], relations=occupied),
    )
    assert planned[0].payload["source_handle"].value != "RIGHT_CENTER"


def test_plan_create_recursive_association_foreign_key() -> None:
    """Verifica que ActionPlanner procese correctamente una relación recursiva 1:N."""
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c_id = uuid4()
    c = DiagramClassSnapshotDto(
        id=c_id,
        name="Empleado",
        position_x=200.0,
        position_y=200.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Empleado",
                "target_class_name": "Empleado",
                "relation_type": "ASSOCIATION",
                "name": "Supervisa",
                "source_cardinality": "0..*",
                "target_cardinality": "0..1",
            },
        )
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 1
    rel_action = planned[0]
    assert rel_action.action_type == AgentActionType.CREATE_RELATION
    assert rel_action.payload["source_class_id"] == c_id
    assert rel_action.payload["target_class_id"] == c_id
    assert rel_action.payload["source_handle"] != rel_action.payload["target_handle"]

    mat = rel_action.payload["materialization"]
    assert mat["strategy"] == "FOREIGN_KEY"
    assert len(mat["foreign_attributes"]) == 1
    fa = mat["foreign_attributes"][0]
    assert fa["class_id"] == str(c_id)
    assert fa["referenced_class_id"] == str(c_id)
    assert fa["is_nullable"] is True


def test_plan_create_recursive_association_many_to_many() -> None:
    """Verifica que ActionPlanner procese correctamente una relación recursiva N:M con clase puente y 2 FKs distintas."""
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c_id = uuid4()
    c = DiagramClassSnapshotDto(
        id=c_id,
        name="Persona",
        position_x=200.0,
        position_y=200.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Persona",
                "target_class_name": "Persona",
                "relation_type": "ASSOCIATION",
                "name": "Conoce",
                "source_cardinality": "0..*",
                "target_cardinality": "0..*",
            },
        )
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 1
    rel_action = planned[0]
    mat = rel_action.payload["materialization"]
    assert mat["strategy"] == "BRIDGE_CLASS"
    bridge = mat["bridge_class"]
    assert len(bridge["foreign_attributes"]) == 2
    fk1, fk2 = bridge["foreign_attributes"]
    assert fk1["name"] != fk2["name"]
    assert fk1["name"] == "persona_a_id"
    assert fk2["name"] == "persona_b_id"
    assert fk1["referenced_class_id"] == str(c_id)
    assert fk2["referenced_class_id"] == str(c_id)


def test_plan_create_recursive_non_association_rejected() -> None:
    """Verifica que intentar auto-relacionar mediante Generalization o Composition lance AgentActionValidationException."""
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c_id = uuid4()
    c = DiagramClassSnapshotDto(
        id=c_id,
        name="Cuenta",
        position_x=200.0,
        position_y=200.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Cuenta",
                "target_class_name": "Cuenta",
                "relation_type": "GENERALIZATION",
            },
        )
    ]

    with pytest.raises(AgentActionValidationException):
        planner.plan_actions(project_id, user_id, actions, snapshot)


def test_plan_create_recursive_association_accepts_valid_proposed_handles() -> None:
    """Verifica que ActionPlanner respete handles propuestos por la IA si son distintos y no están congestionados."""
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"

    c_id = uuid4()
    c = DiagramClassSnapshotDto(
        id=c_id,
        name="Nodo",
        position_x=200.0,
        position_y=200.0,
        attributes=[
            DiagramAttributeSnapshotDto(
                id=uuid4(),
                name="id",
                data_type="UUID",
                position=0,
                is_primary_key=True,
                is_nullable=False,
            )
        ],
    )
    snapshot = DiagramSnapshotDto(classes=[c], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Nodo",
                "target_class_name": "Nodo",
                "relation_type": "ASSOCIATION",
                "source_handle": "TOP_LEFT",
                "target_handle": "TOP_RIGHT",
                "source_cardinality": "0..*",
                "target_cardinality": "0..1",
            },
        )
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    assert len(planned) == 1
    rel_action = planned[0]
    assert rel_action.payload["source_handle"].value == "TOP_LEFT"
    assert rel_action.payload["target_handle"].value == "TOP_RIGHT"


def test_plan_ignores_id_and_foreign_key_attributes_on_create() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"
    snapshot = DiagramSnapshotDto(classes=[], relations=[])

    actions = [
        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "Articulo"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "ID"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "categoria_id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "id_seccion"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "idProveedor"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "titulo"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "idioma"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Articulo", "name": "identificador_legible"}),
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    # Solo deben existir CREATE_CLASS y los 3 atributos legítimos
    assert len(planned) == 4
    attr_names = [a.payload["name"] for a in planned if a.action_type == AgentActionType.CREATE_ATTRIBUTE]
    assert "id" not in attr_names
    assert "ID" not in attr_names
    assert "categoria_id" not in attr_names
    assert "id_seccion" not in attr_names
    assert "idProveedor" not in attr_names
    assert attr_names == ["titulo", "idioma", "identificador_legible"]


def test_plan_user_scenario_producto_venta_bridge_and_aggregation() -> None:
    """
    Escenario exacto del usuario:
    - Producto (id, nombre, precio, imagen)
    - Venta (id, fecha)
    - ProductoVenta (id, producto_id, venta_id, cantidad) - tabla intermedia M:N emitida en el lote
    - Hola (id) con agregación hacia Venta
    - Relación M:N entre Producto y Venta
    - Relación Aggregation entre Hola (origen) y Venta (destino)
    """
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"
    snapshot = DiagramSnapshotDto(classes=[], relations=[])

    actions = [
        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "Producto", "position_x": 100, "position_y": 100}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Producto", "name": "id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Producto", "name": "nombre", "data_type": "TEXT"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Producto", "name": "precio", "data_type": "FLOAT"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Producto", "name": "imagen", "data_type": "TEXT"}),

        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "Venta", "position_x": 600, "position_y": 100}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Venta", "name": "id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Venta", "name": "fecha", "data_type": "DATE"}),

        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "Hola", "position_x": 600, "position_y": 400}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "Hola", "name": "id"}),

        # Clase intermedia redundante emitida por la IA
        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "ProductoVenta"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "ProductoVenta", "name": "id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "ProductoVenta", "name": "producto_id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "ProductoVenta", "name": "venta_id"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "ProductoVenta", "name": "cantidad", "data_type": "INTEGER"}),

        # Relaciones
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Producto",
                "target_class_name": "Venta",
                "relation_type": "ASSOCIATION",
                "name": "Detalle",
                "source_cardinality": "0..*",
                "target_cardinality": "0..*",
            },
        ),
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Hola",
                "target_class_name": "Venta",
                "relation_type": "AGGREGATION",
                "name": "",
            },
        ),
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    # 1. Verificar clases creadas en la fase 1 (Producto, Venta, Hola; ProductoVenta suprimida por redundancia M:N)
    class_actions = [a for a in planned if a.action_type == AgentActionType.CREATE_CLASS]
    created_class_names = [a.payload["name"] for a in class_actions]
    assert "Producto" in created_class_names
    assert "Venta" in created_class_names
    assert "Hola" in created_class_names
    assert "ProductoVenta" not in created_class_names
    assert len(class_actions) == 3

    # 2. Verificar relaciones creadas
    rel_actions = [a for a in planned if a.action_type == AgentActionType.CREATE_RELATION]
    assert len(rel_actions) == 2
    mn_rel = next(r for r in rel_actions if r.payload["materialization"]["strategy"] == "BRIDGE_CLASS")
    agg_rel = next(r for r in rel_actions if r.payload["materialization"]["strategy"] == "FOREIGN_KEY")

    # La clase puente generada es ProductoVenta
    bridge = mn_rel.payload["materialization"]["bridge_class"]
    assert "ProductoVenta" in bridge["name"]
    assert len(bridge["foreign_attributes"]) == 2

    # La agregación coloca FK en Venta (destino)
    venta_action = next(c for c in class_actions if c.payload["name"] == "Venta")
    assert agg_rel.payload["materialization"]["foreign_attributes"][0]["class_id"] == str(venta_action.payload["id"])

    # 3. Verificar atributos
    attr_actions = [a for a in planned if a.action_type == AgentActionType.CREATE_ATTRIBUTE]
    # No debe haber ningún atributo 'id', 'producto_id', ni 'venta_id' creado manualmente
    for a in attr_actions:
        assert a.payload["name"] not in ("id", "producto_id", "venta_id")

    # Producto: nombre, precio, imagen
    prod_id = next(c.payload["id"] for c in class_actions if c.payload["name"] == "Producto")
    prod_attrs = [a.payload["name"] for a in attr_actions if a.payload["class_id"] == prod_id]
    assert sorted(prod_attrs) == ["imagen", "nombre", "precio"]

    # Venta: fecha
    venta_id = venta_action.payload["id"]
    venta_attrs = [a.payload["name"] for a in attr_actions if a.payload["class_id"] == venta_id]
    assert venta_attrs == ["fecha"]

    # Hola: ningún atributo manual (nace con su PK id)
    hola_id = next(c.payload["id"] for c in class_actions if c.payload["name"] == "Hola")
    hola_attrs = [a.payload["name"] for a in attr_actions if a.payload["class_id"] == hola_id]
    assert len(hola_attrs) == 0

    # ProductoVenta (clase puente): cantidad creada en fase 4
    bridge_attrs = [a for a in attr_actions if a.payload["class_id"] == UUID(bridge["id"])]
    assert len(bridge_attrs) == 1
    assert bridge_attrs[0].payload["name"] == "cantidad"


def test_plan_out_of_order_actions_executed_canonically() -> None:
    """Acciones emitidas fuera de orden (relaciones antes de clases, atributos de puente antes de la relación)."""
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "user_1"
    snapshot = DiagramSnapshotDto(classes=[], relations=[])

    # Relación M:N al principio, luego atributos de puente, luego clases
    actions = [
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "A",
                "target_class_name": "B",
                "relation_type": "ASSOCIATION",
                "source_cardinality": "*",
                "target_cardinality": "*",
            },
        ),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "AB", "name": "peso"}),
        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "B"}),
        AiAction(type=AgentActionType.CREATE_CLASS, payload={"name": "A"}),
        AiAction(type=AgentActionType.CREATE_ATTRIBUTE, payload={"class_name": "A", "name": "codigo"}),
    ]

    planned = planner.plan_actions(project_id, user_id, actions, snapshot)

    # Debe ejecutarse sin error
    action_types = [a.action_type for a in planned]
    # Clases primero, luego atributo de A, luego relación M:N, luego atributo de puente
    assert action_types[0] == AgentActionType.CREATE_CLASS
    assert action_types[1] == AgentActionType.CREATE_CLASS
    assert action_types[2] == AgentActionType.CREATE_ATTRIBUTE
    assert action_types[3] == AgentActionType.CREATE_RELATION
    assert action_types[4] == AgentActionType.CREATE_ATTRIBUTE

    assert planned[2].payload["name"] == "codigo"
    assert planned[4].payload["name"] == "peso"


