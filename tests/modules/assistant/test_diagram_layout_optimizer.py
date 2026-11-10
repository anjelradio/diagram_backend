"""Pruebas unitarias para el motor geométrico DiagramLayoutOptimizer y su integración."""

import uuid
import anyio
import pytest
from sqlmodel import Session, select

from app.modules.assistant.application.services.diagram.diagram_layout_optimizer import (
    CLASS_HEIGHT,
    CLASS_WIDTH,
    DiagramLayoutOptimizer,
    MIN_COLLISION_DX,
    MIN_COLLISION_DY,
    SELF_REFERENCE_PAIRS,
    STEP_X,
    STEP_Y,
)
from app.modules.assistant.application.services.diagram.diagram_mutation_tools import (
    DiagramMutationTools,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import DiagramRelationHandle
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from tests.modules.diagram.conftest import create_test_class, create_test_relation


def _run(awaitable):
    result = []

    async def _resolve():
        result.append(await awaitable)

    anyio.run(_resolve)
    return result[0]


@pytest.fixture
def optimizer() -> DiagramLayoutOptimizer:
    return DiagramLayoutOptimizer()


def test_empty_canvas_position(session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer) -> None:
    """En un lienzo vacío, la primera clase se sitúa en las coordenadas mínimas seguras (100.0, 100.0)."""
    pos = optimizer.calculate_class_position(session, test_project.id)
    assert pos == (100.0, 100.0)


def test_radial_candidate_right_free(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Una clase relacionada con otra existente se ubica preferentemente a la derecha."""
    ref_class = create_test_class(session, test_project.id, name="Venta", position_x=100.0, position_y=100.0)
    pos = optimizer.calculate_class_position(session, test_project.id, reference_class_id=ref_class.id)
    assert pos == (100.0 + STEP_X, 100.0)


def test_radial_candidate_bottom_when_right_occupied(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Si el lado derecho está ocupado, la clase se ubica abajo de la referencia."""
    ref_class = create_test_class(session, test_project.id, name="Venta", position_x=100.0, position_y=100.0)
    create_test_class(session, test_project.id, name="Cliente", position_x=100.0 + STEP_X, position_y=100.0)

    pos = optimizer.calculate_class_position(session, test_project.id, reference_class_id=ref_class.id)
    assert pos == (100.0, 100.0 + STEP_Y)


def test_batch_class_position_reservation(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Tres clases creadas en el mismo lote reservan posiciones distintas sin colisionar."""
    reservations: list[tuple[float, float]] = []
    p1 = optimizer.calculate_class_position(session, test_project.id, batch_reserved_positions=reservations)
    p2 = optimizer.calculate_class_position(session, test_project.id, batch_reserved_positions=reservations)
    p3 = optimizer.calculate_class_position(session, test_project.id, batch_reserved_positions=reservations)

    assert len({p1, p2, p3}) == 3
    # Verificar que no colisionen entre sí
    for a in (p1, p2, p3):
        for b in (p1, p2, p3):
            if a != b:
                assert not (abs(a[0] - b[0]) < MIN_COLLISION_DX and abs(a[1] - b[1]) < MIN_COLLISION_DY)


def test_relation_handles_horizontal_left_to_right(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Relación horizontal de izquierda a derecha sale por RIGHT y entra por LEFT."""
    c1 = create_test_class(session, test_project.id, name="Origen", position_x=100.0, position_y=100.0)
    c2 = create_test_class(session, test_project.id, name="Destino", position_x=500.0, position_y=100.0)

    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c2.id)
    assert src_h == DiagramRelationHandle.RIGHT_CENTER
    assert tgt_h == DiagramRelationHandle.LEFT_CENTER


def test_relation_handles_horizontal_right_to_left(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Relación horizontal de derecha a izquierda sale por LEFT y entra por RIGHT."""
    c1 = create_test_class(session, test_project.id, name="Origen", position_x=600.0, position_y=100.0)
    c2 = create_test_class(session, test_project.id, name="Destino", position_x=100.0, position_y=100.0)

    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c2.id)
    assert src_h == DiagramRelationHandle.LEFT_CENTER
    assert tgt_h == DiagramRelationHandle.RIGHT_CENTER


def test_relation_handles_vertical_top_to_bottom(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Relación vertical de arriba hacia abajo sale por BOTTOM y entra por TOP."""
    c1 = create_test_class(session, test_project.id, name="Arriba", position_x=100.0, position_y=100.0)
    c2 = create_test_class(session, test_project.id, name="Abajo", position_x=100.0, position_y=500.0)

    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c2.id)
    assert src_h == DiagramRelationHandle.BOTTOM_CENTER
    assert tgt_h == DiagramRelationHandle.TOP_CENTER


def test_relation_handles_vertical_bottom_to_top(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Relación vertical de abajo hacia arriba sale por TOP y entra por BOTTOM."""
    c1 = create_test_class(session, test_project.id, name="Abajo", position_x=100.0, position_y=500.0)
    c2 = create_test_class(session, test_project.id, name="Arriba", position_x=100.0, position_y=100.0)

    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c2.id)
    assert src_h == DiagramRelationHandle.TOP_CENTER
    assert tgt_h == DiagramRelationHandle.BOTTOM_CENTER


def test_relation_handles_self_reference(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Relación reflexiva asigna un par perimetral válido donde origen != destino."""
    c1 = create_test_class(session, test_project.id, name="Empleado", position_x=100.0, position_y=100.0)

    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c1.id)
    assert src_h != tgt_h
    assert (src_h, tgt_h) in SELF_REFERENCE_PAIRS


def test_relation_handles_occupancy_avoidance(
    session: Session, test_project: ProjectModel, optimizer: DiagramLayoutOptimizer
) -> None:
    """Al existir ya una relación en RIGHT_CENTER y LEFT_CENTER, la siguiente elige otro handle sin solaparse."""
    c1 = create_test_class(session, test_project.id, name="A", position_x=100.0, position_y=100.0)
    c2 = create_test_class(session, test_project.id, name="B", position_x=500.0, position_y=100.0)

    # Crear primera relación usando los handles centrales
    create_test_relation(
        session,
        test_project.id,
        c1.id,
        c2.id,
        source_handle="RIGHT_CENTER",
        target_handle="LEFT_CENTER",
    )

    # La segunda relación no debe usar RIGHT_CENTER ni LEFT_CENTER
    src_h, tgt_h = optimizer.calculate_relation_handles(session, test_project.id, c1.id, c2.id)
    assert src_h != DiagramRelationHandle.RIGHT_CENTER
    assert tgt_h != DiagramRelationHandle.LEFT_CENTER
    assert src_h in (DiagramRelationHandle.RIGHT_BOTTOM, DiagramRelationHandle.RIGHT_TOP, DiagramRelationHandle.BOTTOM_RIGHT)
    assert tgt_h in (DiagramRelationHandle.LEFT_BOTTOM, DiagramRelationHandle.LEFT_TOP, DiagramRelationHandle.BOTTOM_LEFT)


def test_mutation_tools_batch_layout_integration(
    session: Session, test_project: ProjectModel, owner_user
) -> None:
    """apply_diagram_changes ubica clases en lote y conecta relaciones de forma óptima sin colisiones."""
    from app.shared.infrastructure.event_bus_impl import InMemoryEventBus

    uow = SqlModelUnitOfWork(session, InMemoryEventBus())
    mutation_tools = DiagramMutationTools(
        session,
        uow,
        project_id=test_project.id,
        user_id=owner_user.user_id,
    )

    # Acción en lote: Crear Cliente y Venta
    result = _run(
        mutation_tools.apply_diagram_changes(
            {
                "actions": [
                    {
                        "operation_id": "op_c1",
                        "kind": "CREATE_CLASS",
                        "name": "Cliente",
                    },
                    {
                        "operation_id": "op_c2",
                        "kind": "CREATE_CLASS",
                        "name": "Venta",
                    },
                ]
            }
        )
    )
    assert result["status"] == "applied"

    classes = session.exec(
        select(DiagramClassModel).where(DiagramClassModel.project_id == test_project.id)
    ).all()
    assert len(classes) == 2
    c1, c2 = classes[0], classes[1]
    # No colisionan
    assert not (abs(c1.position_x - c2.position_x) < MIN_COLLISION_DX and abs(c1.position_y - c2.position_y) < MIN_COLLISION_DY)
