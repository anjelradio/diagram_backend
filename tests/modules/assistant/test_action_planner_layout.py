import pytest
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.providers.ai_provider import AiAction
from app.modules.assistant.application.services.action_planner import ActionPlanner
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramSnapshotDto,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)


def create_snapshot_with_class(
    class_id: UUID,
    name: str,
    pos_x: float,
    pos_y: float,
) -> DiagramSnapshotDto:
    c = DiagramClassSnapshotDto(
        id=class_id,
        name=name,
        position_x=pos_x,
        position_y=pos_y,
        attributes=[],
    )
    return DiagramSnapshotDto(classes=[c], relations=[])


def test_smart_layout_first_class_places_at_origin() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "test-user"
    snapshot = DiagramSnapshotDto(classes=[], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_CLASS,
            payload={"name": "Usuario"},
        )
    ]

    validated = planner.plan_actions(project_id, user_id, actions, snapshot)
    assert len(validated) == 1
    create_action = validated[0]
    assert create_action.payload["name"] == "Usuario"
    assert create_action.payload["position_x"] >= 100.0
    assert create_action.payload["position_y"] >= 80.0


def test_smart_layout_related_class_places_adjacent_without_collision() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "test-user"
    product_id = uuid4()
    snapshot = create_snapshot_with_class(product_id, "Producto", 160.0, 120.0)

    actions = [
        AiAction(
            type=AgentActionType.CREATE_CLASS,
            payload={"name": "Categoria"},
        ),
        AiAction(
            type=AgentActionType.CREATE_RELATION,
            payload={
                "source_class_name": "Producto",
                "target_class_name": "Categoria",
                "relation_type": "ASSOCIATION",
            },
        ),
    ]

    validated = planner.plan_actions(project_id, user_id, actions, snapshot)
    cat_create = next(a for a in validated if a.action_type == AgentActionType.CREATE_CLASS)
    cat_x = cat_create.payload["position_x"]
    cat_y = cat_create.payload["position_y"]

    # No colisiona con Producto (160, 120)
    dx = abs(cat_x - 160.0)
    dy = abs(cat_y - 120.0)
    # Al menos una dimensión tiene la separación adecuada
    assert dx >= 300.0 or dy >= 200.0
    # Está relativamente cerca de Producto (no a kilómetros)
    assert dx <= 800.0 and dy <= 800.0


def test_smart_layout_unrelated_class_places_near_cluster_without_collision() -> None:
    planner = ActionPlanner()
    project_id = uuid4()
    user_id = "test-user"
    c1 = DiagramClassSnapshotDto(id=uuid4(), name="A", position_x=160.0, position_y=120.0, attributes=[])
    c2 = DiagramClassSnapshotDto(id=uuid4(), name="B", position_x=540.0, position_y=120.0, attributes=[])
    snapshot = DiagramSnapshotDto(classes=[c1, c2], relations=[])

    actions = [
        AiAction(
            type=AgentActionType.CREATE_CLASS,
            payload={"name": "C"},
        )
    ]

    validated = planner.plan_actions(project_id, user_id, actions, snapshot)
    c_create = next(a for a in validated if a.action_type == AgentActionType.CREATE_CLASS)
    cx = c_create.payload["position_x"]
    cy = c_create.payload["position_y"]

    # Verifica que no colisiona con A ni con B
    assert not (abs(cx - 160.0) < 300.0 and abs(cy - 120.0) < 200.0)
    assert not (abs(cx - 540.0) < 300.0 and abs(cy - 120.0) < 200.0)
