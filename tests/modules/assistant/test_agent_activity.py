from uuid import uuid4

from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_activity_state import (
    AgentActivityState,
)


def test_create_agent_activity_sets_in_progress() -> None:
    project_id = uuid4()
    activity = AgentActivity.create(project_id=project_id)

    assert activity.id is not None
    assert activity.project_id == project_id
    assert activity.state == AgentActivityState.IN_PROGRESS
    assert activity.transcription is None
    assert activity.resume is None


def test_finish_agent_activity() -> None:
    project_id = uuid4()
    activity = AgentActivity.create(project_id=project_id)

    activity.finish(
        transcription="Crear clase Usuario",
        resume="Se creó la clase Usuario con éxito.",
    )

    assert activity.state == AgentActivityState.FINISHED
    assert activity.transcription == "Crear clase Usuario"
    assert activity.resume == "Se creó la clase Usuario con éxito."


def test_fail_agent_activity() -> None:
    project_id = uuid4()
    activity = AgentActivity.create(project_id=project_id)

    activity.fail(
        transcription="Orden confusa",
        resume="No se pudo interpretar la orden.",
    )

    assert activity.state == AgentActivityState.FAILED
    assert activity.transcription == "Orden confusa"
    assert activity.resume == "No se pudo interpretar la orden."


def test_cancel_agent_activity() -> None:
    project_id = uuid4()
    activity = AgentActivity.create(project_id=project_id)

    activity.cancel()

    assert activity.state == AgentActivityState.CANCELLED
