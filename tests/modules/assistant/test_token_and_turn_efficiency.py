"""Pruebas unitarias y de integración para la optimización de tokens y eficiencia de turnos."""

import pytest
from uuid import uuid4

from app.core.config import settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiRequest,
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.dialog.turn_interpreter import TurnInterpreter
from app.modules.assistant.application.services.execution.plan_executor import PlanExecutor
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState
from app.modules.assistant.domain.dialog.slot_schema import infer_attribute_type
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan


class CountingAiProvider(AiProvider):
    """Proveedor mock que cuenta exactamente las llamadas realizadas por propósito."""

    def __init__(self, responses: list[AiResult] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return AiResult(
            text="Respuesta por defecto",
            model_role=request.model_role,
            model="counting-mock",
            completed=True,
        )


def _sample_context(prompt: str = "Crea la clase Factura") -> AgentContext:
    return AgentContext(
        user_id="user-1",
        project_id=uuid4(),
        instructions="instrucciones",
        prompt=prompt,
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=5000,
        requires_compaction=False,
    )


def test_infer_attribute_type_by_convention():
    """Valida la inferencia inteligente de tipos de datos según las convenciones comunes."""
    assert infer_attribute_type("id") == "INTEGER"
    assert infer_attribute_type("cliente_id") == "INTEGER"
    assert infer_attribute_type("uuid") == "UUID"
    assert infer_attribute_type("token_uuid") == "UUID"
    assert infer_attribute_type("nombre") == "TEXT"
    assert infer_attribute_type("email") == "TEXT"
    assert infer_attribute_type("descripcion") == "TEXT"
    assert infer_attribute_type("precio") == "DECIMAL"
    assert infer_attribute_type("total") == "DECIMAL"
    assert infer_attribute_type("saldo") == "DECIMAL"
    assert infer_attribute_type("stock") == "INTEGER"
    assert infer_attribute_type("edad") == "INTEGER"
    assert infer_attribute_type("activo") == "BOOLEAN"
    assert infer_attribute_type("es_admin") == "BOOLEAN"
    assert infer_attribute_type("habilitado") == "BOOLEAN"
    assert infer_attribute_type("fecha_nacimiento") == "DATE"
    assert infer_attribute_type("created_at") == "TIMESTAMP"
    assert infer_attribute_type("actualizado_en") == "TIMESTAMP"
    # Fallback por defecto seguro para UML
    assert infer_attribute_type("campo_personalizado") == "TEXT"
    assert infer_attribute_type(None) == "TEXT"


def test_tool_pruning_filters_history_tools():
    """Valida que en tareas de mutación se poden las herramientas de historial conversacional."""
    registry = ToolRegistry()

    # Registrar herramientas simuladas
    from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition

    registry.register(
        RegisteredTool(
            AiToolDefinition("apply_diagram_changes", "Aplica cambios", {}),
            lambda *args: {},
            mutating=True,
        )
    )
    registry.register(
        RegisteredTool(
            AiToolDefinition("get_diagram_element", "Consulta elemento", {}),
            lambda *args: {},
            mutating=False,
        )
    )
    registry.register(
        RegisteredTool(
            AiToolDefinition("search_project_conversation", "Busca historial", {}),
            lambda *args: {},
            mutating=False,
        )
    )
    registry.register(
        RegisteredTool(
            AiToolDefinition("get_project_conversation_message", "Lee mensaje", {}),
            lambda *args: {},
            mutating=False,
        )
    )

    # Con include_history=False (poda activa):
    pruned = registry.definitions_for_task(mutation_allowed=True, include_history=False)
    pruned_names = {t.name for t in pruned}
    assert "apply_diagram_changes" in pruned_names
    assert "get_diagram_element" in pruned_names
    assert "search_project_conversation" not in pruned_names
    assert "get_project_conversation_message" not in pruned_names

    # Con include_history=True:
    full = registry.definitions_for_task(mutation_allowed=True, include_history=True)
    full_names = {t.name for t in full}
    assert "search_project_conversation" in full_names
    assert "get_project_conversation_message" in full_names


@pytest.mark.anyio
async def test_fast_synthesis_bypasses_final_llm_call_on_successful_mutation():
    """Valida que con fast_synthesis=True, una mutación exitosa no gaste una llamada extra de síntesis."""
    provider = CountingAiProvider(
        [
            # Respuesta a la tarea de mutación: ejecuta la herramienta
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall("call-1", "apply_diagram_changes", {"actions": [{"action": "CREATE_CLASS", "name": "Factura"}]}),
                ),
            ),
            # Respuesta del LLM confirmando la tarea
            AiResult(text="Clase creada", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition

    async def fake_handler(args, report):
        return {
            "results": [{"status": "applied", "operation_id": "op-1", "kind": "CREATE_CLASS", "name": "Factura"}],
            "mutation_applied": True,
            "entity_refs": [{"type": "class", "id": str(uuid4())}],
        }

    registry.register(
        RegisteredTool(
            AiToolDefinition("apply_diagram_changes", "Aplica cambios", {}),
            fake_handler,
            mutating=True,
        )
    )

    plan = ExecutionPlan.create(
        goal="Crear Factura",
        tasks=[{"id": "task-1", "objective": "Crear Factura", "kind": "mutation"}],
    )

    # Ejecutar con fast_synthesis=True
    executor = PlanExecutor(provider, registry, fast_synthesis=True)
    result = await executor.execute(_sample_context("Crea la clase Factura"), plan)

    assert result.completed is True
    # Solo 2 llamadas: (1) tool call + (2) tool response completion.
    # CERO llamadas para síntesis (_synthesize cortocircuitado).
    assert len(provider.requests) == 2
    assert "Se creó" in result.text or "Factura" in result.text
    assert result.metadata.get("fast_synthesis") is True


@pytest.mark.anyio
async def test_fast_synthesis_disabled_runs_llm_synthesis():
    """Valida que con fast_synthesis=False, se preserva la llamada a síntesis LLM habitual."""
    provider = CountingAiProvider(
        [
            AiResult(
                text="",
                model_role=ModelRole.MAIN,
                model="qwen",
                tool_calls=(
                    AiToolCall("call-1", "apply_diagram_changes", {"actions": []}),
                ),
            ),
            AiResult(text="Tarea lista", model_role=ModelRole.MAIN, model="qwen"),
            # Tercera llamada: síntesis final
            AiResult(text="Resumen sintetizado por LLM", model_role=ModelRole.MAIN, model="qwen"),
        ]
    )
    registry = ToolRegistry()

    from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition

    async def fake_handler(args, report):
        return {"results": [{"status": "applied"}], "mutation_applied": True}

    registry.register(
        RegisteredTool(
            AiToolDefinition("apply_diagram_changes", "Aplica cambios", {}),
            fake_handler,
            mutating=True,
        )
    )

    plan = ExecutionPlan.create(
        goal="Crear Factura",
        tasks=[{"id": "task-1", "objective": "Crear Factura", "kind": "mutation"}],
    )

    executor = PlanExecutor(provider, registry, fast_synthesis=False)
    result = await executor.execute(_sample_context("Crea la clase Factura"), plan)

    assert result.completed is True
    # 3 llamadas en total (incluyendo la síntesis LLM)
    assert len(provider.requests) == 3
    assert result.text == "Resumen sintetizado por LLM"


@pytest.mark.anyio
async def test_turn_interpreter_adopts_default_cardinalities():
    """Valida que expresiones coloquiales como 'por defecto' o 'la típica' resuelvan cardinalidades 1 a 0..*."""
    interpreter = TurnInterpreter(ai_provider=None)

    frame = DialogFrame(id="f1", action="CREATE_RELATION")
    frame.set_slot("relation.source_class", "Factura")
    frame.set_slot("relation.target_class", "DetalleFactura")
    frame.set_slot("relation.type", "ASSOCIATION")
    frame.evaluate_readiness()

    state = DialogState(frames=[frame])

    # El usuario responde 'por defecto'
    turn = await interpreter.interpret(
        user_message="por defecto",
        dialog_state=state,
    )

    assert turn.user_act == "provide_slots"
    assert turn.slots.get("relation.source_cardinality") == "1"
    assert turn.slots.get("relation.target_cardinality") == "0..*"

    # El usuario responde 'la típica'
    turn2 = await interpreter.interpret(
        user_message="la típica",
        dialog_state=state,
    )
    assert turn2.user_act == "provide_slots"
    assert turn2.slots.get("relation.source_cardinality") == "1"
    assert turn2.slots.get("relation.target_cardinality") == "0..*"
