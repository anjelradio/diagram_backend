import pytest
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    AiResult,
    AiToolCall,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.execution.plan_executor import PlanExecutor
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan


class RecordingProvider(AiProvider):
    def __init__(self, responses: list[AiResult]) -> None:
        self.responses = list(responses)
        self.recorded_requests: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.recorded_requests.append(request)
        if not self.responses:
            return AiResult(text="Done.", model_role=request.model_role, model="mock")
        return self.responses.pop(0)


def _build_context(prompt: str) -> AgentContext:
    from uuid import uuid4
    return AgentContext(
        user_id="user-1",
        project_id=uuid4(),
        instructions="Test",
        prompt=prompt,
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=1000,
        requires_compaction=False,
    )


@pytest.mark.anyio
async def test_executor_caches_search_diagram_elements():
    """Verifica que llamadas sucesivas a search_diagram_elements con mismos argumentos usan el caché."""
    call_count = 0

    async def mock_search(arguments, report=None):
        nonlocal call_count
        call_count += 1
        return {
            "status": "ok",
            "items": [{"type": "class", "id": "uuid-prod", "name": "Producto"}],
        }

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(
                name="search_diagram_elements",
                description="search",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
            mock_search,
            mutating=False,
        )
    )

    # Tarea 1: busca Producto
    # Tarea 2: vuelve a buscar Producto
    search_call = AiToolCall(
        id="call-1",
        name="search_diagram_elements",
        arguments={"query": "Producto"},
    )
    search_call_2 = AiToolCall(
        id="call-2",
        name="search_diagram_elements",
        arguments={"query": "Producto"},
    )

    provider = RecordingProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(search_call,)),
            AiResult(text="Encontré Producto.", model_role=ModelRole.MAIN, model="mock"),
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(search_call_2,)),
            AiResult(text="Sigo con Producto.", model_role=ModelRole.MAIN, model="mock"),
        ]
    )

    executor = PlanExecutor(provider, registry)
    plan = ExecutionPlan(
        goal="Consultas",
        tasks=[
            {"id": "t1", "objective": "Buscar producto 1", "kind": "answer", "status": "pending"},
            {"id": "t2", "objective": "Buscar producto 2", "kind": "answer", "depends_on": ["t1"], "status": "pending"},
        ],
    )

    result = await executor.execute(_build_context("Busca producto"), plan)
    assert result.completed is True
    # La herramienta real solo debe haberse invocado 1 VEZ; la segunda fue CACHE HIT
    assert call_count == 1


@pytest.mark.anyio
async def test_executor_invalidates_cache_on_mutation():
    """Verifica que una mutación invalida el caché de búsqueda."""
    search_count = 0

    async def mock_search(arguments, report=None):
        nonlocal search_count
        search_count += 1
        return {
            "status": "ok",
            "items": [{"type": "class", "id": "uuid-prod", "name": "Producto"}],
        }

    async def mock_mutate(arguments, report=None):
        return {
            "status": "applied",
            "operation_id": "op-1",
            "results": [
                {
                    "status": "applied",
                    "entity_refs": [{"type": "class", "id": "uuid-prod"}],
                }
            ],
        }

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(
                name="search_diagram_elements",
                description="search",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
            mock_search,
            mutating=False,
        )
    )
    registry.register(
        RegisteredTool(
            AiToolDefinition(
                name="apply_diagram_changes",
                description="mutate",
                parameters={"type": "object", "properties": {"actions": {"type": "array"}}},
            ),
            mock_mutate,
            mutating=True,
        )
    )

    search_call_1 = AiToolCall(id="c1", name="search_diagram_elements", arguments={"query": "Producto"})
    mutate_call = AiToolCall(
        id="c2",
        name="apply_diagram_changes",
        arguments={"actions": [{"kind": "MODIFY_CLASS", "name": "Producto"}]},
    )
    search_call_2 = AiToolCall(id="c3", name="search_diagram_elements", arguments={"query": "Producto"})

    provider = RecordingProvider(
        [
            # Tarea 1: busca Producto (se cachea) y luego muta Producto (invalida caché)
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(search_call_1,)),
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(mutate_call,)),
            AiResult(text="Modificado.", model_role=ModelRole.MAIN, model="mock"),
            # Tarea 2: vuelve a buscar Producto post mutación (debe ser cache miss e invocar mock_search de nuevo)
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(search_call_2,)),
            AiResult(text="Listo.", model_role=ModelRole.MAIN, model="mock"),
        ]
    )

    executor = PlanExecutor(provider, registry)
    plan = ExecutionPlan(
        goal="Mutar y buscar",
        tasks=[
            {"id": "t1", "objective": "Modificar producto", "kind": "mutation", "status": "pending"},
            {"id": "t2", "objective": "Buscar producto post mutación", "kind": "answer", "depends_on": ["t1"], "status": "pending"},
        ],
    )

    result = await executor.execute(_build_context("Mutar producto"), plan)
    assert result.completed is True
    # search_count debe ser 2 porque la mutación invalidó el caché
    assert search_count == 2


@pytest.mark.anyio
async def test_executor_pre_injects_known_classes_into_subsequent_tasks():
    """Verifica que las clases encontradas o creadas se pre-inyectan en mensajes de tareas siguientes."""
    async def mock_search(arguments, report=None):
        return {
            "status": "ok",
            "items": [{"type": "class", "id": "uuid-prod-100", "name": "Producto"}],
        }

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(
                name="search_diagram_elements",
                description="search",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
            mock_search,
            mutating=False,
        )
    )

    search_call = AiToolCall(id="c1", name="search_diagram_elements", arguments={"query": "Producto"})
    provider = RecordingProvider(
        [
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=(search_call,)),
            AiResult(text="Encontrado.", model_role=ModelRole.MAIN, model="mock"),
            AiResult(text="Finalizado.", model_role=ModelRole.MAIN, model="mock"),
        ]
    )

    executor = PlanExecutor(provider, registry)
    plan = ExecutionPlan(
        goal="Dos tareas",
        tasks=[
            {"id": "t1", "objective": "Buscar Producto", "kind": "answer", "status": "pending"},
            {"id": "t2", "objective": "Usar Producto", "kind": "answer", "depends_on": ["t1"], "status": "pending"},
        ],
    )

    await executor.execute(_build_context("Test pre-injection"), plan)

    # Revisar las solicitudes registradas en la tarea 2
    # El proveedor debe haber recibido una solicitud con el mensaje de clases conocidas
    task_2_requests = [
        req for req in provider.recorded_requests
        if any("Clases conocidas previamente en el diagrama" in (m.content if isinstance(m.content, str) else "") for m in req.messages)
    ]
    assert len(task_2_requests) >= 1
    # Verificar que contiene 'producto' y el ID
    content_str = str([m.content for m in task_2_requests[0].messages])
    assert "producto" in content_str.lower()
    assert "uuid-prod-100" in content_str


@pytest.mark.anyio
async def test_executor_selects_execution_role_when_expected_actions_present():
    """Verifica que el ejecutor selecciona ModelRole.EXECUTION cuando la tarea tiene expected_actions."""
    registry = ToolRegistry()
    provider = RecordingProvider([AiResult(text="Atributos agregados.", model_role=ModelRole.EXECUTION, model="mock")])
    executor = PlanExecutor(provider, registry)

    plan = ExecutionPlan(
        goal="Agregar atributos",
        tasks=[
            {
                "id": "t1",
                "objective": "Crea atributos",
                "kind": "mutation",
                "status": "pending",
                "expected_actions": [{"kind": "CREATE_ATTRIBUTE", "class_name": "Producto"}],
            }
        ],
    )

    await executor.execute(_build_context("Agrega atributos"), plan)
    assert len(provider.recorded_requests) >= 1
    # La solicitud debió solicitar ModelRole.EXECUTION
    assert provider.recorded_requests[0].model_role == ModelRole.EXECUTION


@pytest.mark.anyio
async def test_executor_preseeds_classes_from_class_provider():
    """Verifica que PlanExecutor pre-carga las clases del proyecto en tool_cache desde class_provider."""
    registry = ToolRegistry()
    provider = RecordingProvider([AiResult(text="Entendido.", model_role=ModelRole.MAIN, model="mock")])

    def mock_class_provider(proj_id):
        return {"Pedido": "uuid-pedido-123", "Producto": "uuid-prod-456"}

    executor = PlanExecutor(provider, registry, class_provider=mock_class_provider)

    plan = ExecutionPlan(
        goal="Consultar clases",
        tasks=[
            {
                "id": "t1",
                "objective": "Consultar relación",
                "kind": "answer",
                "status": "pending",
            }
        ],
    )

    await executor.execute(_build_context("¿Cómo relaciono Pedido y Producto?"), plan)

    assert len(provider.recorded_requests) >= 1
    prompt_messages = provider.recorded_requests[0].messages
    known_msg = next(
        (m for m in prompt_messages if "Clases conocidas previamente en el diagrama" in (m.content or "")),
        None,
    )
    assert known_msg is not None
    assert "uuid-pedido-123" in known_msg.content
    assert "uuid-prod-456" in known_msg.content


@pytest.mark.anyio
async def test_executor_disallows_mutation_tools_for_answer_kind_tasks():
    """Verifica que una tarea kind='answer' no reciba apply_diagram_changes entre sus herramientas."""
    registry = ToolRegistry()
    # Registrar herramienta mutadora
    registry.register(
        RegisteredTool(
            AiToolDefinition(name="apply_diagram_changes", description="mutar", parameters={"type": "object"}),
            lambda args: {"status": "ok"},
            mutating=True,
        )
    )
    # Registrar herramienta de lectura
    registry.register(
        RegisteredTool(
            AiToolDefinition(name="search_diagram_elements", description="buscar", parameters={"type": "object"}),
            lambda args: {"status": "ok"},
            mutating=False,
        )
    )

    provider = RecordingProvider([AiResult(text="Respuesta conceptual.", model_role=ModelRole.MAIN, model="mock")])
    executor = PlanExecutor(provider, registry)

    plan = ExecutionPlan(
        goal="Pregunta conceptual",
        tasks=[
            {
                "id": "t1",
                "objective": "¿Cómo debería relacionar Pedido con Producto?",
                "kind": "answer",
                "status": "pending",
            }
        ],
    )

    await executor.execute(_build_context("¿Cómo debería relacionar Pedido con Producto?"), plan)

    assert len(provider.recorded_requests) >= 1
    offered_tools = provider.recorded_requests[0].tools or ()
    offered_tool_names = {t.name for t in offered_tools}

    assert "search_diagram_elements" in offered_tool_names
    assert "apply_diagram_changes" not in offered_tool_names


@pytest.mark.anyio
async def test_executor_tolerates_spurious_mutation_call_with_text_in_answer_task():
    """Si el modelo emite apply_diagram_changes en una tarea de consulta pero ya generó texto sustancial, no falla."""
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(name="search_diagram_elements", description="buscar", parameters={"type": "object"}),
            lambda args: {"status": "ok"},
            mutating=False,
        )
    )

    answer_text = (
        "Ambas clases existen en el diagrama: **Pedido** y **Producto**. "
        "Para modelar compras donde un pedido puede incluir varios productos con cantidad "
        "y precio unitario, se recomienda crear una clase asociativa intermedia llamada **DetallePedido**."
    )
    spurious_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": []},
    )

    provider = RecordingProvider([
        AiResult(
            text=answer_text,
            model_role=ModelRole.MAIN,
            model="mock",
            tool_calls=(spurious_call,),
        )
    ])
    executor = PlanExecutor(provider, registry)

    plan = ExecutionPlan(
        goal="Pregunta conceptual",
        tasks=[
            {
                "id": "direct",
                "objective": "¿Cómo debería relacionar Pedido con Producto?",
                "kind": "answer",
                "status": "pending",
            }
        ],
    )

    result = await executor.execute(_build_context("¿Cómo debería relacionar Pedido con Producto?"), plan)

    assert result.completed is True
    assert "DetallePedido" in result.text
    assert "no se completó toda la solicitud" not in result.text.lower()
    assert "revisa los cambios confirmados" not in result.text.lower()


@pytest.mark.anyio
async def test_executor_anti_mutation_directive_injected_for_answer_tasks():
    """Verifica que para tareas de consulta se inyecta la directiva explícita anti-mutación."""
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(name="search_diagram_elements", description="buscar", parameters={"type": "object"}),
            lambda args: {"status": "ok"},
            mutating=False,
        )
    )

    provider = RecordingProvider([AiResult(text="Explicación conceptual.", model_role=ModelRole.MAIN, model="mock")])
    executor = PlanExecutor(provider, registry)

    plan = ExecutionPlan(
        goal="Pregunta",
        tasks=[
            {
                "id": "t1",
                "objective": "Explicar arquitectura",
                "kind": "answer",
                "status": "pending",
            }
        ],
    )

    await executor.execute(_build_context("Explicar arquitectura"), plan)

    assert len(provider.recorded_requests) >= 1
    req_messages = provider.recorded_requests[0].messages
    anti_mutation_msg = next(
        (m for m in req_messages if "Esta tarea es exclusivamente de consulta" in (m.content or "")),
        None,
    )
    assert anti_mutation_msg is not None
    assert "NO modifiques el diagrama" in anti_mutation_msg.content


def test_failure_notice_behavior_across_scenarios():
    """Verifica el comportamiento contextual de _failure_notice según el tipo de plan."""
    from app.modules.assistant.application.services.execution.plan_executor import _failure_notice

    # 1. Plan de consulta o conceptual (answer/query): no añade aviso de diagrama
    query_plan = ExecutionPlan(
        goal="Consulta",
        tasks=[{"id": "t1", "kind": "answer", "status": "failed"}],
    )
    notice_query = _failure_notice("Explicación sobre pedidos.", query_plan)
    assert notice_query == "Explicación sobre pedidos."
    assert "diagrama" not in notice_query.lower()

    # 2. Plan de mutación con 0 cambios aplicados: informa con precisión sin pedir revisar
    mutate_plan_empty = ExecutionPlan(
        goal="Crear clase",
        tasks=[{"id": "t1", "kind": "create", "status": "failed"}],
        operation_ledger=[],
    )
    notice_empty = _failure_notice("Error al procesar la clase.", mutate_plan_empty)
    assert "No se aplicaron cambios en el diagrama." in notice_empty
    assert "revisa los cambios confirmados" not in notice_empty.lower()

    # 3. Plan con cambios parciales confirmados: mantiene el aviso de revisar cambios confirmados
    mutate_plan_partial = ExecutionPlan(
        goal="Crear clases",
        tasks=[
            {"id": "t1", "kind": "create", "status": "completed"},
            {"id": "t2", "kind": "create", "status": "failed"},
        ],
        operation_ledger=[{"operation_id": "op-1", "status": "applied"}],
    )
    notice_partial = _failure_notice("Se creó una de dos clases.", mutate_plan_partial)
    assert "No se completó toda la solicitud. Revisa los cambios confirmados en el diagrama" in notice_partial


@pytest.mark.anyio
async def test_executor_fails_cleanly_when_spurious_mutation_has_no_text():
    """Si el modelo emite apply_diagram_changes sin texto en una tarea de consulta, falla limpiamente sin aviso de diagrama."""
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(name="search_diagram_elements", description="buscar", parameters={"type": "object"}),
            lambda args: {"status": "ok"},
            mutating=False,
        )
    )

    spurious_call = AiToolCall(
        id="c1",
        name="apply_diagram_changes",
        arguments={"actions": []},
    )

    provider = RecordingProvider([
        AiResult(
            text="",
            model_role=ModelRole.MAIN,
            model="mock",
            tool_calls=(spurious_call,),
        ),
        AiResult(
            text="No pude consultar la información.",
            model_role=ModelRole.MAIN,
            model="mock",
        ),
    ])
    executor = PlanExecutor(provider, registry)

    plan = ExecutionPlan(
        goal="Pregunta",
        tasks=[
            {
                "id": "direct",
                "objective": "Consultar relaciones",
                "kind": "answer",
                "status": "pending",
            }
        ],
    )

    result = await executor.execute(_build_context("Consultar relaciones"), plan)

    assert result.completed is False
    assert "revisa los cambios confirmados" not in result.text.lower()


