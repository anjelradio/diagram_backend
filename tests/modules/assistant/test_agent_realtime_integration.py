import anyio
from datetime import datetime, timezone
from math import ceil
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

from app.modules.assistant.infrastructure.realtime import agent_completion_publisher
from app.modules.assistant.infrastructure.realtime.agent_completion_publisher import (
    WebSocketAgentCompletionPublisher,
)
from app.modules.assistant.infrastructure.realtime.agent_activity_publisher import (
    WebSocketAgentActivityPublisher,
)
from app.modules.assistant.application.ports.agent_activity_publisher import (
    AgentActivity,
    AgentActivityCode,
)
from app.modules.assistant.application.services.agent_activity_reporter import (
    AgentActivityReporter,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    ClientSession,
    ConnectionManager,
)


def test_completion_publisher_sends_correlated_terminal_event(monkeypatch):
    calls = []

    class FakeConnectionManager:
        async def broadcast_agent_message_finished(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        agent_completion_publisher,
        "connection_manager",
        FakeConnectionManager(),
    )
    project_id, message_id = uuid4(), uuid4()

    async def run():
        await WebSocketAgentCompletionPublisher().publish_finished(
            project_id=project_id,
            user_id="user-owner",
            message_id=message_id,
            prompt="Create a class",
            image_url=None,
            status="failed",
            response_markdown="No se pudo completar.",
            created_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            author_name="Ada",
            author_avatar_url="https://cdn.example.test/ada.png",
        )

    anyio.run(run)

    assert calls == [
        {
            "project_id": project_id,
            "user_id": "user-owner",
            "message_id": message_id,
            "prompt": "Create a class",
            "image_url": None,
            "status": "failed",
            "response_markdown": "No se pudo completar.",
            "created_at": datetime(2026, 11, 4, tzinfo=timezone.utc),
            "author_name": "Ada",
            "author_avatar_url": "https://cdn.example.test/ada.png",
        }
    ]


def test_completion_publisher_sends_correlated_partial_terminal_event(monkeypatch):
    # T009 [US1]: El evento final de completitud publica status='partial' correlacionado con message_id
    calls = []

    class FakeConnectionManager:
        async def broadcast_agent_message_finished(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        agent_completion_publisher,
        "connection_manager",
        FakeConnectionManager(),
    )
    project_id, message_id = uuid4(), uuid4()

    async def run():
        await WebSocketAgentCompletionPublisher().publish_finished(
            project_id=project_id,
            user_id="user-owner",
            message_id=message_id,
            prompt="Crear clases",
            image_url=None,
            status="partial",
            response_markdown="Se completó 1 tarea y 1 quedó pendiente.",
            created_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            author_name="Ada",
            author_avatar_url="https://cdn.example.test/ada.png",
        )

    anyio.run(run)

    assert calls == [
        {
            "project_id": project_id,
            "user_id": "user-owner",
            "message_id": message_id,
            "prompt": "Crear clases",
            "image_url": None,
            "status": "partial",
            "response_markdown": "Se completó 1 tarea y 1 quedó pendiente.",
            "created_at": datetime(2026, 11, 4, tzinfo=timezone.utc),
            "author_name": "Ada",
            "author_avatar_url": "https://cdn.example.test/ada.png",
        }
    ]



def test_terminal_message_is_broadcast_only_to_project_sessions():
    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    project_id, other_project_id, message_id = uuid4(), uuid4(), uuid4()
    owner_socket, collaborator_socket, other_socket = FakeSocket(), FakeSocket(), FakeSocket()
    manager = ConnectionManager()
    manager.sessions[project_id] = [
        ClientSession(owner_socket, project_id, "owner", "Owner", "owner"),
        ClientSession(collaborator_socket, project_id, "collaborator", "Member", "editor"),
    ]
    manager.sessions[other_project_id] = [
        ClientSession(other_socket, other_project_id, "outsider", "Outsider", "editor")
    ]

    async def run():
        await manager.broadcast_agent_message_finished(
            project_id=project_id,
            user_id="owner",
            message_id=message_id,
            prompt="Create Product",
            image_url=None,
            status="completed",
            response_markdown="Created **Product**.",
            created_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            author_name="Owner",
            author_avatar_url="https://cdn.example.test/owner.png",
        )

    anyio.run(run)

    assert len(owner_socket.messages) == 1
    assert owner_socket.messages == collaborator_socket.messages
    assert other_socket.messages == []
    assert owner_socket.messages[0]["type"] == "agent_message_finished"
    assert owner_socket.messages[0]["message_id"] == str(message_id)
    assert owner_socket.messages[0]["user_id"] == "owner"
    assert owner_socket.messages[0]["status"] == "completed"
    assert owner_socket.messages[0]["response_markdown"] == "Created **Product**."
    assert owner_socket.messages[0]["author_avatar_url"] == "https://cdn.example.test/owner.png"


def test_accepted_message_is_broadcast_only_to_project_sessions():
    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    project_id, other_project_id, message_id = uuid4(), uuid4(), uuid4()
    owner_socket, collaborator_socket, other_socket = FakeSocket(), FakeSocket(), FakeSocket()
    manager = ConnectionManager()
    manager.sessions[project_id] = [
        ClientSession(owner_socket, project_id, "owner", "Owner", "owner"),
        ClientSession(collaborator_socket, project_id, "collaborator", "Member", "editor"),
    ]
    manager.sessions[other_project_id] = [
        ClientSession(other_socket, other_project_id, "outsider", "Outsider", "editor")
    ]

    async def run():
        await manager.broadcast_agent_message_accepted(
            project_id=project_id,
            message_id=message_id,
            user_id="owner",
            author_name="Owner",
            author_avatar_url=None,
            prompt="Create Product",
            image_url=None,
            status="running",
            cancel_requested=False,
            response_markdown=None,
            created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
        )

    anyio.run(run)

    assert len(owner_socket.messages) == 1
    assert owner_socket.messages == collaborator_socket.messages
    assert other_socket.messages == []
    event = owner_socket.messages[0]
    assert event["type"] == "agent_message_accepted"
    assert event["message_id"] == str(message_id)
    assert event["user_id"] == "owner"
    assert event["author_avatar_url"] is None


def test_acceptance_adapter_is_best_effort(monkeypatch):
    import app.modules.assistant.infrastructure.realtime.agent_acceptance_publisher as acceptance_adapter
    from app.modules.assistant.infrastructure.realtime.agent_acceptance_publisher import WebSocketAgentAcceptancePublisher

    class BrokenConnectionManager:
        async def broadcast_agent_message_accepted(self, **_event):
            raise RuntimeError("socket unavailable")

    monkeypatch.setattr(
        acceptance_adapter,
        "connection_manager",
        BrokenConnectionManager(),
    )

    async def run():
        await WebSocketAgentAcceptancePublisher().publish_accepted(
            project_id=uuid4(),
            message_id=uuid4(),
            user_id="owner",
            author_name="Owner",
            author_avatar_url=None,
            prompt="Create Product",
            image_url=None,
            status="running",
            cancel_requested=False,
            response_markdown=None,
            created_at=datetime.now(timezone.utc),
        )

    anyio.run(run)


def test_activity_publisher_sends_only_allowlisted_activity_fields(monkeypatch):
    calls = []

    class FakeConnectionManager:
        async def broadcast_agent_message_activity(self, **event):
            calls.append(event)

    from app.modules.assistant.infrastructure.realtime import agent_activity_publisher

    monkeypatch.setattr(agent_activity_publisher, "connection_manager", FakeConnectionManager())
    project_id, message_id, attempt_id = uuid4(), uuid4(), uuid4()
    occurred_at = datetime(2026, 11, 5, tzinfo=timezone.utc)

    async def run():
        await WebSocketAgentActivityPublisher().publish_activity(
            AgentActivity(
                project_id=project_id,
                message_id=message_id,
                attempt_id=attempt_id,
                sequence=2,
                code=AgentActivityCode.PLANNING,
                occurred_at=occurred_at,
            )
        )

    anyio.run(run)

    assert calls == [
        {
            "project_id": project_id,
            "message_id": message_id,
            "attempt_id": attempt_id,
            "sequence": 2,
            "activity_code": "planning",
            "activity_type": "planning",
            "occurred_at": occurred_at,
        }
    ]


def test_activity_reporter_stops_after_attempt_is_cancelled():
    calls = []

    class Publisher:
        async def publish_activity(self, activity):
            calls.append(activity)

    stopped = anyio.Event()
    stopped.set()
    reporter = AgentActivityReporter(
        Publisher(),
        project_id=uuid4(),
        message_id=uuid4(),
        attempt_id=uuid4(),
        stopped=stopped,
    )

    async def run():
        await reporter.report(AgentActivityCode.FINALIZING)

    anyio.run(run)
    assert calls == []


def test_local_activity_broadcast_p95_stays_below_two_seconds():
    class TimedSocket:
        def __init__(self):
            self.received_at = []

        async def send_json(self, _payload):
            self.received_at.append(perf_counter())

    project_id, message_id, attempt_id = uuid4(), uuid4(), uuid4()
    sockets = [TimedSocket() for _ in range(8)]
    manager = ConnectionManager()
    manager.sessions[project_id] = [
        ClientSession(socket, project_id, f"user-{index}", f"User {index}", "editor")
        for index, socket in enumerate(sockets)
    ]
    latencies = []

    async def run():
        for sequence in range(1, 101):
            started_at = perf_counter()
            await manager.broadcast_agent_message_activity(
                project_id=project_id,
                message_id=message_id,
                attempt_id=attempt_id,
                sequence=sequence,
                activity_code="planning",
                occurred_at=datetime.now(timezone.utc),
            )
            delivered_at = max(socket.received_at[-1] for socket in sockets)
            latencies.append(delivered_at - started_at)

    anyio.run(run)

    assert all(len(socket.received_at) == 100 for socket in sockets)
    p95_index = ceil(len(latencies) * 0.95) - 1
    assert sorted(latencies)[p95_index] < 2.0


def test_connected_asgi_websocket_receives_real_activity_under_two_seconds(
    client,
    session,
    collaborative_project,
    owner_user,
    monkeypatch,
):
    from app.modules.diagram.infrastructure.api.routers import diagram_ws_router
    from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole

    monkeypatch.setattr(diagram_ws_router, "engine", session.get_bind())
    monkeypatch.setattr(
        diagram_ws_router, "get_ws_auth_user", lambda _websocket: owner_user
    )
    monkeypatch.setattr(
        diagram_ws_router,
        "get_ws_project_access",
        lambda *_args: SimpleNamespace(access_role=ProjectAccessRole.OWNER),
    )

    project_id, message_id, attempt_id = (
        collaborative_project.id,
        uuid4(),
        uuid4(),
    )
    reporter = AgentActivityReporter(
        WebSocketAgentActivityPublisher(),
        project_id=project_id,
        message_id=message_id,
        attempt_id=attempt_id,
    )
    latencies = []

    with client.websocket_connect(f"/api/ws/projects/{project_id}?token=local-test") as socket:
        assert socket.receive_json()["type"] == "presence_snapshot"

        for sequence in range(1, 101):
            started_at = perf_counter()
            socket.portal.call(reporter.report, AgentActivityCode.PLANNING)
            event = socket.receive_json()
            latencies.append(perf_counter() - started_at)
            assert event["type"] == "agent_message_activity"
            assert event["project_id"] == str(project_id)
            assert event["message_id"] == str(message_id)
            assert event["attempt_id"] == str(attempt_id)
            assert event["sequence"] == sequence

    p95_index = ceil(len(latencies) * 0.95) - 1
    assert len(latencies) == 100
    assert sorted(latencies)[p95_index] < 2.0


def test_recalling_conversation_activity_broadcast_contains_no_historical_content(monkeypatch):
    """T026 [US3]: La actividad 'recalling_conversation' emite tipo 'query' y jamás filtra contenido."""
    calls = []

    class FakeConnectionManager:
        async def broadcast_agent_message_activity(self, **event):
            calls.append(event)

    from app.modules.assistant.infrastructure.realtime import agent_activity_publisher

    monkeypatch.setattr(agent_activity_publisher, "connection_manager", FakeConnectionManager())
    project_id, message_id, attempt_id = uuid4(), uuid4(), uuid4()
    occurred_at = datetime(2026, 11, 5, tzinfo=timezone.utc)

    activity = AgentActivity(
        project_id=project_id,
        message_id=message_id,
        attempt_id=attempt_id,
        sequence=3,
        code=AgentActivityCode.RECALLING_CONVERSATION,
        occurred_at=occurred_at,
    )

    async def run():
        await WebSocketAgentActivityPublisher().publish_activity(activity)

    anyio.run(run)

    assert len(calls) == 1
    event = calls[0]
    assert event["activity_code"] == "recalling_conversation"
    assert event["activity_type"] == "query"
    # Campos estrictamente permitidos en el wire protocol; sin consultas ni textos históricos
    allowed_keys = {
        "project_id",
        "message_id",
        "attempt_id",
        "sequence",
        "activity_code",
        "activity_type",
        "occurred_at",
    }
    assert set(event.keys()) == allowed_keys


def test_terminal_domain_failure_realtime_broadcast_uses_standard_event_and_deterministic_markdown():
    """T020 [US3]: Publicación realtime de fallo terminal usa 'agent_message_finished', status 'failed' y Markdown local."""
    from app.modules.assistant.application.services.execution.terminal_failure import (
        DomainFailureCategory,
        TerminalToolFailure,
        format_terminal_failure_markdown,
    )

    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    project_id = uuid4()
    other_project_id = uuid4()
    message_id = uuid4()

    owner_socket = FakeSocket()
    collaborator_socket = FakeSocket()
    outsider_socket = FakeSocket()

    manager = ConnectionManager()
    manager.sessions[project_id] = [
        ClientSession(owner_socket, project_id, "user-owner", "Owner", "owner"),
        ClientSession(collaborator_socket, project_id, "user-collab", "Collaborator", "editor"),
    ]
    manager.sessions[other_project_id] = [
        ClientSession(outsider_socket, other_project_id, "user-outsider", "Outsider", "editor"),
    ]

    failure = TerminalToolFailure(
        category=DomainFailureCategory.CLASS_NOT_FOUND,
        affected_element_type="class",
        display_name="Factura",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        error_code="class_not_found",
        has_confirmed_changes=True,
    )
    deterministic_markdown = format_terminal_failure_markdown(failure)

    async def run():
        await manager.broadcast_agent_message_finished(
            project_id=project_id,
            user_id="user-owner",
            message_id=message_id,
            prompt="Eliminar clase Factura",
            image_url=None,
            status="failed",
            response_markdown=deterministic_markdown,
            created_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
            author_name="Owner",
            author_avatar_url="https://cdn.example.test/owner.png",
        )

    anyio.run(run)

    # 1. Ambos clientes del proyecto reciben el mensaje
    assert len(owner_socket.messages) == 1
    assert len(collaborator_socket.messages) == 1
    assert owner_socket.messages == collaborator_socket.messages

    # 2. Clientes de otros proyectos no reciben nada
    assert outsider_socket.messages == []

    # 3. El tipo de evento es estrictamente el evento existente (sin nuevos tipos WS)
    event = owner_socket.messages[0]
    assert event["type"] == "agent_message_finished"
    assert event["status"] == "failed"
    assert event["message_id"] == str(message_id)
    assert event["user_id"] == "user-owner"
    assert event["response_markdown"] == deterministic_markdown

    # 4. Contenido seguro y cordial en Markdown
    assert "No se pudo completar la solicitud porque la clase **Factura** ya no está disponible" in event["response_markdown"]
    assert "Los cambios confirmados y aplicados anteriormente en esta solicitud se conservan intactos en el diagrama." in event["response_markdown"]
    assert "Te sugerimos revisar el diagrama antes de volver a intentarlo." in event["response_markdown"]

    # 5. Esquema del wire protocol sin campos internos ni filtraciones
    expected_wire_keys = {
        "type",
        "project_id",
        "message_id",
        "user_id",
        "prompt",
        "image_url",
        "status",
        "response_markdown",
        "created_at",
        "author_name",
        "author_avatar_url",
    }
    assert set(event.keys()) == expected_wire_keys


def test_read_tools_reserves_exact_components_on_get_and_not_on_search():
    """T013 [US1]: DiagramReadTools._get emite reservas QUERY en IDs exactos (clase, atributo, relación con extremos), mientras _search no emite reservas."""
    from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
        AgentComponentReservationEvent,
        AgentComponentReservationPublisher,
        AgentReservationActivityType,
        AgentReservationComponentType,
    )
    from app.modules.assistant.application.services.diagram.diagram_read_tools import (
        DiagramReadTools,
    )
    from app.modules.assistant.application.services.diagram.agent_reservation_emitter import (
        AgentReservationEmitter,
    )

    published_events: list[AgentComponentReservationEvent] = []

    class FakeReservationPublisher(AgentComponentReservationPublisher):
        async def publish_reservation(self, event: AgentComponentReservationEvent) -> None:
            published_events.append(event)

        async def publish_release(self, project_id, message_id) -> None:
            pass

    project_id = uuid4()
    message_id = uuid4()
    user_id = "test-user"
    class_id = uuid4()
    attr_id = uuid4()
    rel_id = uuid4()
    source_class_id = uuid4()
    target_class_id = uuid4()

    class FakeQueryResult:
        def __init__(self, element_type, id_, name, details):
            self.element_type = element_type
            self.id = id_
            self.name = name
            self.details = details

    class FakeSearchItem:
        def __init__(self, element_type, id_, name, owner_class_id=None):
            self.element_type = element_type
            self.id = id_
            self.name = name
            self.owner_class_id = owner_class_id

    class FakeSearchResult:
        def __init__(self, items):
            self.items = items
            self.ambiguous_names = []
            self.has_more = False
            self.next_offset = None

    class FakeQueryHandler:
        def get(self, query):
            if query.element_type == "class" and query.element_id == class_id:
                return FakeQueryResult("class", class_id, "User", {})
            if query.element_type == "attribute" and query.element_id == attr_id:
                return FakeQueryResult("attribute", attr_id, "email", {"class_id": str(class_id)})
            if query.element_type == "relation" and query.element_id == rel_id:
                return FakeQueryResult(
                    "relation",
                    rel_id,
                    "owns",
                    {
                        "source_class_id": str(source_class_id),
                        "target_class_id": str(target_class_id),
                    },
                )
            return None

        def search(self, query):
            return FakeSearchResult(
                [FakeSearchItem("class", class_id, "User")]
            )

    publisher = FakeReservationPublisher()
    emitter = AgentReservationEmitter(
        publisher,
        project_id=project_id,
        message_id=message_id,
    )
    tools = DiagramReadTools(
        query_handler=FakeQueryHandler(),
        project_id=project_id,
        user_id=user_id,
        message_id=message_id,
        reservation_emitter=emitter,
    )

    async def run():
        # 1. _search no emite reservas
        search_res = await tools._search({"query": "User"})
        assert search_res["status"] == "ok"
        assert len(published_events) == 0

        # 2. _get de clase emite reserva query para class_id
        get_class_res = await tools._get({"type": "class", "id": str(class_id)})
        assert get_class_res["type"] == "class"
        assert len(published_events) == 1
        assert published_events[0].component_type == AgentReservationComponentType.CLASS
        assert published_events[0].component_id == class_id
        assert published_events[0].activity_type == AgentReservationActivityType.QUERY
        assert published_events[0].sequence == 1

        # 3. _get de atributo emite reserva query para su clase propietaria
        get_attr_res = await tools._get({"type": "attribute", "id": str(attr_id)})
        assert get_attr_res["type"] == "attribute"
        assert len(published_events) == 2
        assert published_events[1].component_type == AgentReservationComponentType.CLASS
        assert published_events[1].component_id == class_id
        assert published_events[1].activity_type == AgentReservationActivityType.QUERY
        assert published_events[1].sequence == 2

        # 4. _get de relación emite reserva query para relación y extremos
        get_rel_res = await tools._get({"type": "relation", "id": str(rel_id)})
        assert get_rel_res["type"] == "relation"
        assert len(published_events) == 5
        assert published_events[2].component_type == AgentReservationComponentType.RELATION
        assert published_events[2].component_id == rel_id
        assert published_events[3].component_type == AgentReservationComponentType.CLASS
        assert published_events[3].component_id == source_class_id
        assert published_events[4].component_type == AgentReservationComponentType.CLASS
        assert published_events[4].component_id == target_class_id

    anyio.run(run)


def test_agent_component_reservation_broadcast_to_websocket_clients():
    """T013 [US1]: Difusión de agent_component_reserved llega con esquema wire completo y aísla proyectos ajenos."""
    from app.modules.assistant.application.ports.agent_component_reservation_publisher import (
        AgentComponentReservationEvent,
        AgentReservationActivityType,
        AgentReservationComponentType,
    )
    from app.modules.assistant.infrastructure.realtime.agent_component_reservation_publisher import (
        WebSocketAgentComponentReservationPublisher,
    )
    from app.modules.assistant.infrastructure.realtime import (
        agent_component_reservation_publisher as adapter_module,
    )

    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    project_id = uuid4()
    other_project_id = uuid4()
    message_id = uuid4()
    class_id = uuid4()
    attr_id = uuid4()

    owner_socket = FakeSocket()
    collab_socket = FakeSocket()
    other_socket = FakeSocket()

    manager = ConnectionManager()
    manager.sessions[project_id] = [
        ClientSession(owner_socket, project_id, "user-owner", "Owner", "owner"),
        ClientSession(collab_socket, project_id, "user-collab", "Collab", "editor"),
    ]
    manager.sessions[other_project_id] = [
        ClientSession(other_socket, other_project_id, "user-outsider", "Outsider", "editor"),
    ]

    async def run():
        event = AgentComponentReservationEvent(
            project_id=project_id,
            message_id=message_id,
            sequence=1,
            component_type=AgentReservationComponentType.CLASS,
            component_id=class_id,
            activity_type=AgentReservationActivityType.EDIT,
            attribute_id=attr_id,
        )
        orig_cm = adapter_module.connection_manager
        adapter_module.connection_manager = manager
        try:
            publisher = WebSocketAgentComponentReservationPublisher()
            await publisher.publish_reservation(event)
        finally:
            adapter_module.connection_manager = orig_cm

    anyio.run(run)

    assert len(owner_socket.messages) == 1
    assert len(collab_socket.messages) == 1
    assert other_socket.messages == []

    msg = owner_socket.messages[0]
    assert msg["type"] == "agent_component_reserved"
    assert msg["project_id"] == str(project_id)
    assert msg["message_id"] == str(message_id)
    assert msg["sequence"] == 1
    assert msg["component_type"] == "class"
    assert msg["component_id"] == str(class_id)
    assert msg["activity_type"] == "edit"
    assert msg["attribute_id"] == str(attr_id)

    assert set(msg.keys()) == {
        "type",
        "project_id",
        "message_id",
        "sequence",
        "component_type",
        "component_id",
        "activity_type",
        "attribute_id",
    }


def test_completion_publisher_releases_reservations_on_terminal(monkeypatch):
    # T019/T022: WebSocketAgentCompletionPublisher emite agent_component_reservations_released en estado terminal
    finished_calls = []
    released_calls = []

    class FakeConnectionManager:
        async def broadcast_agent_message_finished(self, **kwargs):
            finished_calls.append(kwargs)

        async def broadcast_agent_component_reservations_released(self, **kwargs):
            released_calls.append(kwargs)

    monkeypatch.setattr(
        agent_completion_publisher,
        "connection_manager",
        FakeConnectionManager(),
    )
    project_id, message_id = uuid4(), uuid4()

    async def run():
        await WebSocketAgentCompletionPublisher().publish_finished(
            project_id=project_id,
            user_id="user-owner",
            message_id=message_id,
            prompt="Crear clase",
            image_url=None,
            status="completed",
            response_markdown="Listo.",
            created_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            author_name="Ada",
            author_avatar_url=None,
        )

    anyio.run(run)

    assert len(finished_calls) == 1
    assert len(released_calls) == 1
    assert released_calls[0] == {
        "project_id": project_id,
        "message_id": message_id,
    }


def test_room_state_selective_message_release_and_retention():
    # T020/T022: Dos mensajes concurrentes; liberar msg1 conserva las reservas de msg2
    from app.modules.diagram.infrastructure.realtime.room_state import ProjectRoomState

    project_id = uuid4()
    msg1_id = uuid4()
    msg2_id = uuid4()
    class1_id = uuid4()
    class2_id = uuid4()

    room = ProjectRoomState(project_id)
    room.reserve_component(
        project_id=project_id,
        message_id=msg1_id,
        sequence=1,
        component_type="class",
        component_id=class1_id,
        activity_type="query",
    )
    room.reserve_component(
        project_id=project_id,
        message_id=msg2_id,
        sequence=1,
        component_type="class",
        component_id=class2_id,
        activity_type="edit",
    )

    assert room.is_component_reserved(class1_id, "class")
    assert room.is_component_reserved(class2_id, "class")

    released = room.release_message_reservations(msg1_id)
    assert len(released) == 1
    assert released[0].component_id == class1_id

    # class1 liberada, class2 sigue reservada por msg2
    assert not room.is_component_reserved(class1_id, "class")
    assert room.is_component_reserved(class2_id, "class")
    assert room.has_active_reservations()


def test_room_state_out_of_order_sequence_and_edit_promotion():
    # T020/T022: Evento fuera de orden no degrada secuencia ni 'edit'
    from app.modules.diagram.infrastructure.realtime.room_state import ProjectRoomState

    project_id = uuid4()
    message_id = uuid4()
    class_id = uuid4()
    attr_id = uuid4()

    room = ProjectRoomState(project_id)
    # Llega primero seq 2 (query con attr)
    res1 = room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=2,
        component_type="class",
        component_id=class_id,
        activity_type="query",
        attribute_id=attr_id,
    )
    assert res1.sequence == 2
    assert res1.activity_type == "query"

    # Llega tarde seq 1 (edit sin attr)
    res2 = room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="edit",
        attribute_id=None,
    )
    # Se promueve a edit, pero la secuencia se mantiene en 2 y no borra attr_id
    assert res2.sequence == 2
    assert res2.activity_type == "edit"
    assert res2.attribute_id == attr_id


def test_room_state_snapshot_purges_expired_reservations():
    # T020/T022: Presencia snapshot purga reservas expiradas por TTL
    from app.modules.diagram.infrastructure.realtime.room_state import ProjectRoomState

    project_id = uuid4()
    message_id = uuid4()
    class_id = uuid4()

    room = ProjectRoomState(project_id)
    room.reserve_component(
        project_id=project_id,
        message_id=message_id,
        sequence=1,
        component_type="class",
        component_id=class_id,
        activity_type="edit",
        now=100.0,
    )

    # A t=150s (dentro de TTL 300s): la reserva está viva
    active_snapshot = room.serialize_reservations(now=150.0)
    assert len(active_snapshot) == 1
    assert active_snapshot[0]["component_id"] == str(class_id)

    # A t=450s (>300s TTL): la reserva ha expirado y se purga
    expired_snapshot = room.serialize_reservations(now=450.0)
    assert len(expired_snapshot) == 0
    assert not room.has_active_reservations(now=450.0)


def test_cancel_agent_message_use_case_publishes_release():
    # T019/T022: CancelAgentMessageUseCase invoca publish_release_sync
    from app.modules.assistant.application.use_cases.cancel_agent_message import (
        CancelAgentMessageUseCase,
    )
    from app.modules.assistant.domain.entities.agent_message import AgentMessage
    from app.modules.assistant.domain.enums.agent_message_status import AgentMessageStatus

    project_id = uuid4()
    message_id = uuid4()
    user_id = "user-alice"

    released_calls = []

    class FakePublisher:
        def publish_release_sync(self, pid, mid):
            released_calls.append((pid, mid))

    class FakeRepo:
        def __init__(self):
            self.msg = AgentMessage(
                id=message_id,
                project_id=project_id,
                user_id=user_id,
                prompt="Crear clase",
                status=AgentMessageStatus.RUNNING,
            )

        def request_cancel(self, message_id, project_id, user_id, now):
            self.msg.cancel_requested = True
            return self.msg

        def find_by_id(self, mid):
            return self.msg

    class FakePolicy:
        def ensure_read_access(self, pid, uid):
            pass

    class FakeUoW:
        def commit(self):
            pass

        def rollback(self):
            pass

    use_case = CancelAgentMessageUseCase(
        message_repository=FakeRepo(),
        project_access_policy=FakePolicy(),
        uow=FakeUoW(),
        reservation_publisher=FakePublisher(),
    )

    result = use_case.execute(
        message_id=message_id,
        project_id=project_id,
        user_id=user_id,
    )

    assert result.cancellation_pending is True
    assert released_calls == [(project_id, message_id)]




