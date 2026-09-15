import pytest
from uuid import uuid4

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
