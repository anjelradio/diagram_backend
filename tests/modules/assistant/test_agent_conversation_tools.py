from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from sqlmodel import Session

from app.modules.assistant.application.services.diagram.agent_conversation_tools import (
    AgentConversationTools,
)
from app.modules.assistant.application.services.execution.tool_registry import ToolRegistry
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.readers.sqlmodel_agent_conversation_reader import (
    SQLModelAgentConversationReader,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel


def _add_message(
    session: Session,
    project_id,
    user_id: str,
    *,
    prompt: str,
    response: str,
    created_at: datetime,
    status: str = "completed",
    plan: dict | None = None,
    deleted: bool = False,
) -> AgentMessageModel:
    msg = AgentMessageModel(
        id=uuid4(),
        project_id=project_id,
        user_id=user_id,
        prompt=prompt,
        response_markdown=response,
        status=status,
        plan=plan,
        created_date=created_at,
        deleted_date=created_at if deleted else None,
    )
    session.add(msg)
    session.commit()
    return msg


def _make_tools(session: Session, project_id, user_id: str, max_total_chars: int = 4000) -> AgentConversationTools:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access_policy = ProjectAccessPolicy(project_repo, member_repo)
    reader = SQLModelAgentConversationReader(session)
    return AgentConversationTools(
        conversation_reader=reader,
        access_policy=access_policy,
        project_id=project_id,
        user_id=user_id,
        max_total_chars=max_total_chars,
    )


@pytest.mark.anyio
async def test_conversation_tools_pagination_and_cursor(session, test_project, owner_user):
    """T029 [US5]: search_project_conversation pagina correctamente usando cursor opaco."""
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    for i in range(5):
        _add_message(
            session,
            test_project.id,
            owner_user.user_id,
            prompt=f"Mensaje {i}",
            response=f"Respuesta {i}",
            created_at=base_time + timedelta(minutes=i),
        )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    # Primera página: 2 elementos (más recientes primero)
    first_page = await registry.execute("search_project_conversation", {"limit": 2})
    assert first_page["status"] == "ok"
    assert len(first_page["items"]) == 2
    assert first_page["has_more"] is True
    assert first_page["next_cursor"] is not None
    assert first_page["items"][0]["prompt_excerpt"] == "Mensaje 4"
    assert first_page["items"][1]["prompt_excerpt"] == "Mensaje 3"

    # Segunda página con cursor
    second_page = await registry.execute(
        "search_project_conversation",
        {"limit": 2, "cursor": first_page["next_cursor"]},
    )
    assert second_page["status"] == "ok"
    assert len(second_page["items"]) == 2
    assert second_page["items"][0]["prompt_excerpt"] == "Mensaje 2"
    assert second_page["items"][1]["prompt_excerpt"] == "Mensaje 1"
    assert second_page["has_more"] is True

    # Tercera página
    third_page = await registry.execute(
        "search_project_conversation",
        {"limit": 2, "cursor": second_page["next_cursor"]},
    )
    assert third_page["status"] == "ok"
    assert len(third_page["items"]) == 1
    assert third_page["items"][0]["prompt_excerpt"] == "Mensaje 0"
    assert third_page["has_more"] is False
    assert third_page["next_cursor"] is None


@pytest.mark.anyio
async def test_conversation_tools_limit_validation(session, test_project, owner_user):
    """T029 [US5]: Límite estrictamente acotado entre 1 y 5; argumentos inválidos rechazados."""
    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"limit": 0})

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"limit": 6})

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"limit": "dos"})

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"cursor": "x" * 300})

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute(
            "search_project_conversation",
            {"limit": 2, "unexpected_key": "injected"},
        )


@pytest.mark.anyio
async def test_conversation_tools_isolation_and_authorization(session, test_project, owner_user):
    """T029 [US5]: Solo se consultan mensajes del proyecto; usuarios sin acceso reciben forbidden."""
    base_time = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Mensaje proyecto autorizado",
        response="OK",
        created_at=base_time,
    )

    # Otro proyecto distinto persistido
    other_project = ProjectModel(
        owner_id=owner_user.user_id, name="Otro proyecto", id=uuid4()
    )
    session.add(other_project)
    session.flush()
    _add_message(
        session,
        other_project.id,
        owner_user.user_id,
        prompt="Mensaje otro proyecto",
        response="Secreto",
        created_at=base_time,
    )

    # Consulta con usuario autorizado en test_project
    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    result = await registry.execute("search_project_conversation", {"limit": 5})
    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    assert result["items"][0]["prompt_excerpt"] == "Mensaje proyecto autorizado"

    # Consulta con usuario no autorizado o sin membresía
    unauthorized_tools = _make_tools(session, test_project.id, "attacker-user-id")
    unauthorized_registry = ToolRegistry()
    unauthorized_tools.register(unauthorized_registry)

    forbidden_result = await unauthorized_registry.execute("search_project_conversation", {"limit": 5})
    assert forbidden_result == {"status": "forbidden", "error_code": "forbidden"}


@pytest.mark.anyio
async def test_conversation_tools_budget_and_truncation(session, test_project, owner_user):
    """T029 [US5]: Presupuesto máximo de 4000 caracteres trunca mensajes extensos."""
    base_time = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    # Mensaje muy largo que excede el presupuesto
    long_prompt = "P" * 2500
    long_response = "R" * 2000
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt=long_prompt,
        response=long_response,
        created_at=base_time,
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id, max_total_chars=1000)
    registry = ToolRegistry()
    tools.register(registry)

    result = await registry.execute("search_project_conversation", {"limit": 1})
    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    assert result["truncated"] is True
    # El contenido fue truncado para no exceder los 1000 caracteres
    item = result["items"][0]
    total_len = len(item["prompt_excerpt"]) + len(item["response_excerpt"])
    assert total_len <= 1000


@pytest.mark.anyio
async def test_conversation_tools_soft_deleted_messages_are_excluded(session, test_project, owner_user):
    """T029 [US5]: Los mensajes con soft-delete no se devuelven en la consulta."""
    base_time = datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Mensaje activo",
        response="Activo",
        created_at=base_time,
        deleted=False,
    )
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Mensaje borrado",
        response="Borrado",
        created_at=base_time + timedelta(minutes=1),
        deleted=True,
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    result = await registry.execute("search_project_conversation", {"limit": 5})
    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    assert result["items"][0]["prompt_excerpt"] == "Mensaje activo"


@pytest.mark.anyio
async def test_conversation_tools_scope_mine_vs_project(session, test_project, owner_user):
    """US3: scope='mine' solo devuelve mensajes del usuario; scope='project' incluye colaboradores."""
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Mi mensaje",
        response="Mi respuesta",
        created_at=base_time,
    )
    _add_message(
        session,
        test_project.id,
        "collab-user-2",
        prompt="Mensaje colaborador",
        response="Respuesta colaborador",
        created_at=base_time + timedelta(minutes=1),
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    # Por defecto scope='mine'
    res_mine = await registry.execute("search_project_conversation", {})
    assert res_mine["status"] == "ok"
    assert len(res_mine["items"]) == 1
    assert res_mine["items"][0]["prompt_excerpt"] == "Mi mensaje"

    # scope='project'
    res_project = await registry.execute("search_project_conversation", {"scope": "project"})
    assert res_project["status"] == "ok"
    assert len(res_project["items"]) == 2


@pytest.mark.anyio
async def test_conversation_tools_status_completed_only(session, test_project, owner_user):
    """US3: Solo los mensajes completados son recuperados por search y get."""
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    completed_msg = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Completado",
        response="Hecho",
        created_at=base_time,
        status="completed",
    )
    running_msg = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="En ejecucion",
        response=None,
        created_at=base_time + timedelta(minutes=1),
        status="running",
    )
    failed_msg = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Fallido",
        response=None,
        created_at=base_time + timedelta(minutes=2),
        status="failed",
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    res_search = await registry.execute("search_project_conversation", {})
    assert res_search["status"] == "ok"
    assert len(res_search["items"]) == 1
    assert res_search["items"][0]["message_id"] == str(completed_msg.id)

    res_get_running = await registry.execute(
        "get_project_conversation_message", {"message_id": str(running_msg.id)}
    )
    assert res_get_running["status"] == "not_found"

    res_get_failed = await registry.execute(
        "get_project_conversation_message", {"message_id": str(failed_msg.id)}
    )
    assert res_get_failed["status"] == "not_found"


@pytest.mark.anyio
async def test_conversation_tools_query_text_and_escaping(session, test_project, owner_user):
    """US3: Filtro textual busca en prompt o respuesta y escapa comodines SQL."""
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Diagramar arquitectura hexagonal",
        response="Entendido, arquitectura creada",
        created_at=base_time,
    )
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Crear tablas de postgres",
        response="Base de datos configurada al 100%_final",
        created_at=base_time + timedelta(minutes=1),
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    # Coincidencia por prompt
    res1 = await registry.execute("search_project_conversation", {"query": "hexagonal"})
    assert res1["status"] == "ok"
    assert len(res1["items"]) == 1
    assert "hexagonal" in res1["items"][0]["prompt_excerpt"]

    # Coincidencia por response
    res2 = await registry.execute("search_project_conversation", {"query": "configurada"})
    assert res2["status"] == "ok"
    assert len(res2["items"]) == 1
    assert "postgres" in res2["items"][0]["prompt_excerpt"]

    # Escapar comodín: 100%_final solo coincide con el segundo, no con ambos
    res3 = await registry.execute("search_project_conversation", {"query": "100%_final"})
    assert res3["status"] == "ok"
    assert len(res3["items"]) == 1
    assert "postgres" in res3["items"][0]["prompt_excerpt"]

    # Validación de longitud mínima
    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"query": "a"})


@pytest.mark.anyio
async def test_conversation_tools_before_filter(session, test_project, owner_user):
    """US3: before excluye mensajes con fecha igual o posterior."""
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)
    t2 = t0 + timedelta(hours=2)

    _add_message(session, test_project.id, owner_user.user_id, prompt="M0", response="R0", created_at=t0)
    _add_message(session, test_project.id, owner_user.user_id, prompt="M1", response="R1", created_at=t1)
    _add_message(session, test_project.id, owner_user.user_id, prompt="M2", response="R2", created_at=t2)

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    res = await registry.execute("search_project_conversation", {"before": t2.isoformat()})
    assert res["status"] == "ok"
    assert len(res["items"]) == 2
    assert [item["prompt_excerpt"] for item in res["items"]] == ["M1", "M0"]

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"before": "invalid-date"})


@pytest.mark.anyio
async def test_conversation_tools_cursor_bound_to_filters(session, test_project, owner_user):
    """US3: El cursor está estrictamente ligado al query, scope y before empleados."""
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Alpha 1",
        response="OK",
        created_at=base_time,
    )
    _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Alpha 2",
        response="OK",
        created_at=base_time + timedelta(minutes=1),
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    page1 = await registry.execute("search_project_conversation", {"query": "Alpha", "limit": 1})
    assert page1["has_more"] is True
    cursor = page1["next_cursor"]
    assert cursor is not None

    # Usar cursor con filtro cambiado produce error de argumentos
    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"query": "Beta", "cursor": cursor})

    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("search_project_conversation", {"query": "Alpha", "scope": "project", "cursor": cursor})


@pytest.mark.anyio
async def test_conversation_tools_get_project_conversation_message(session, test_project, owner_user):
    """US3: get_project_conversation_message devuelve operaciones confirmadas y respeta permisos."""
    plan_data = {
        "operation_ledger": [
            {
                "operation_id": "op-1",
                "action_kind": "CREATE_CLASS",
                "entity_refs": [{"type": "class", "name": "Servicio de Usuarios"}],
                "status": "applied",
            },
            {
                "operation_id": "op-2",
                "action_kind": "DELETE_CLASS",
                "entity_refs": [{"type": "class", "name": "temp-1"}],
                "status": "rejected",
            },
            {
                "operation_id": "op-3",
                "action_kind": "CREATE_RELATION",
                "entity_refs": [{"type": "relation", "name": "rel-1"}],
                "status": "failed",
            },
        ]
    }
    msg = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Crear nodo de usuarios",
        response="Nodo creado con éxito.",
        created_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        plan=plan_data,
    )

    collab_msg = _add_message(
        session,
        test_project.id,
        "collab-user-99",
        prompt="Pregunta colaborador",
        response="Respuesta a colaborador",
        created_at=datetime(2026, 3, 1, 12, 5, tzinfo=timezone.utc),
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    # Detalle con éxito y operaciones solo 'applied'
    detail = await registry.execute("get_project_conversation_message", {"message_id": str(msg.id)})
    assert detail["status"] == "ok"
    assert detail["message_id"] == str(msg.id)
    assert detail["prompt_excerpt"] == "Crear nodo de usuarios"
    assert detail["response_excerpt"] == "Nodo creado con éxito."
    assert "Creación de clase" in detail["confirmed_operations"][0]
    assert "Servicio de Usuarios" in detail["confirmed_operations"][0]
    assert "DELETE_CLASS" not in str(detail["confirmed_operations"])
    assert "CREATE_RELATION" not in str(detail["confirmed_operations"])

    # ID inexistente
    not_found = await registry.execute(
        "get_project_conversation_message", {"message_id": str(uuid4())}
    )
    assert not_found["status"] == "not_found"

    # ID inválido
    with pytest.raises(AgentToolArgumentsException):
        await registry.execute("get_project_conversation_message", {"message_id": "not-a-uuid"})

    # Mensaje de otro usuario con scope='mine' (default) -> not_found
    other_mine = await registry.execute(
        "get_project_conversation_message", {"message_id": str(collab_msg.id), "scope": "mine"}
    )
    assert other_mine["status"] == "not_found"

    # Mensaje de otro usuario con scope='project' -> ok
    other_proj = await registry.execute(
        "get_project_conversation_message", {"message_id": str(collab_msg.id), "scope": "project"}
    )
    assert other_proj["status"] == "ok"
    assert other_proj["prompt_excerpt"] == "Pregunta colaborador"


@pytest.mark.anyio
async def test_search_and_detail_support_terminal_statuses_with_outcome_and_only_applied_operations(
    session: Session, test_project: ProjectModel, owner_user
):
    """Verifica que completed/failed/cancelled con respuesta sean consultables con outcome y solo operaciones applied."""
    now = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

    # 1. Mensaje completado con outcome success y 1 operación aplicada
    msg_completed = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Crear clase Pedido",
        response="Clase Pedido creada exitosamente.",
        created_at=now,
        status="completed",
        plan={
            "outcome": "success",
            "operation_ledger": [
                {
                    "operation_id": "op-1",
                    "action_kind": "CREATE_CLASS",
                    "entity_refs": [{"type": "class", "name": "Pedido"}],
                    "status": "applied",
                }
            ],
        },
    )

    # 2. Mensaje fallido pero con respuesta parcial (outcome partial, 1 applied y 1 failed)
    msg_failed_partial = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Crear Producto y Factura",
        response="Se creó Producto pero falló Factura.",
        created_at=now + timedelta(minutes=1),
        status="failed",
        plan={
            "metadata": {"outcome": "partial"},
            "operation_ledger": [
                {
                    "operation_id": "op-2",
                    "action_kind": "CREATE_CLASS",
                    "entity_refs": [{"type": "class", "name": "Producto"}],
                    "status": "applied",
                },
                {
                    "operation_id": "op-3",
                    "action_kind": "CREATE_CLASS",
                    "entity_refs": [{"type": "class", "name": "Factura"}],
                    "status": "failed",
                },
            ],
        },
    )

    # 3. Mensaje cancelado con respuesta
    msg_cancelled = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Crear relación",
        response="Cancelado a petición del usuario.",
        created_at=now + timedelta(minutes=2),
        status="cancelled",
    )

    # 4. Mensaje fallido SIN respuesta markdown
    msg_failed_no_response = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="Error fatal antes de responder",
        response="",
        created_at=now + timedelta(minutes=3),
        status="failed",
    )

    # 5. Mensaje en ejecución (running)
    msg_running = _add_message(
        session,
        test_project.id,
        owner_user.user_id,
        prompt="En ejecución actualmente",
        response="Borrador temporal",
        created_at=now + timedelta(minutes=4),
        status="running",
    )

    tools = _make_tools(session, test_project.id, owner_user.user_id)
    registry = ToolRegistry()
    tools.register(registry)

    # Búsqueda en historial
    search_res = await registry.execute("search_project_conversation", {"limit": 5})
    assert search_res["status"] == "ok"
    returned_ids = [item["message_id"] for item in search_res["items"]]

    # Debe incluir los 3 mensajes terminales con respuesta
    assert str(msg_completed.id) in returned_ids
    assert str(msg_failed_partial.id) in returned_ids
    assert str(msg_cancelled.id) in returned_ids

    # NO debe incluir el fallido sin respuesta ni el running
    assert str(msg_failed_no_response.id) not in returned_ids
    assert str(msg_running.id) not in returned_ids

    # Verificar status y outcome expuestos en cada extracto
    items_by_id = {item["message_id"]: item for item in search_res["items"]}
    assert items_by_id[str(msg_completed.id)]["status"] == "completed"
    assert items_by_id[str(msg_completed.id)]["outcome"] == "success"

    assert items_by_id[str(msg_failed_partial.id)]["status"] == "failed"
    assert items_by_id[str(msg_failed_partial.id)]["outcome"] == "partial"

    assert items_by_id[str(msg_cancelled.id)]["status"] == "cancelled"

    # Detalle de mensaje fallido con respuesta: solo expone operaciones confirmadas (applied)
    detail_failed = await registry.execute(
        "get_project_conversation_message", {"message_id": str(msg_failed_partial.id)}
    )
    assert detail_failed["status"] == "ok"
    assert detail_failed["message_status"] == "failed"
    assert detail_failed["outcome"] == "partial"
    assert len(detail_failed["confirmed_operations"]) == 1
    assert "Producto" in detail_failed["confirmed_operations"][0]
    assert "Factura" not in str(detail_failed["confirmed_operations"])

    # Detalle de fallido sin respuesta -> not_found
    detail_no_resp = await registry.execute(
        "get_project_conversation_message", {"message_id": str(msg_failed_no_response.id)}
    )
    assert detail_no_resp["status"] == "not_found"

    # Detalle de running -> not_found
    detail_running = await registry.execute(
        "get_project_conversation_message", {"message_id": str(msg_running.id)}
    )
    assert detail_running["status"] == "not_found"

