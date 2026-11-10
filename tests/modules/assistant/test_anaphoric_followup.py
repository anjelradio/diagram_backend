"""Tests para la resolución de anáforas, continuidad conversacional e inyección de historial."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiRequest,
    AiResult,
    AiToolCall,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    RecentExchange,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.dialog.dialog_manager import (
    extract_proposals_from_recent_exchanges,
)
from app.modules.assistant.application.services.dialog.dialog_policy import DialogPolicy
from app.modules.assistant.application.services.dialog.turn_interpreter import TurnInterpreter
from app.modules.assistant.application.services.execution.plan_executor import PlanExecutor
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    has_direct_mutation_command,
    requires_mutation,
)
from app.modules.assistant.domain.dialog.dialog_frame import DialogState
from app.modules.assistant.application.services.execution.tool_registry import ToolRegistry


class RecordingAiProvider(AiProvider):
    """Mock AiProvider que registra las llamadas y solicitudes completadas."""

    def __init__(self, responses: list[AiResult] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResult:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return AiResult(
            text="Operación completada con éxito.",
            model_role=request.model_role,
            model="mock",
            completed=True,
        )





def test_anaphoric_intent_classification():
    """Valida que las frases anafóricas e imperativas sean catalogadas como mutación."""
    mutation_prompts = [
        "Aplica esa generalización en las clases",
        "Aplica esa generalización",
        "Conéctalas",
        "Conéctalas con herencia",
        "Haz esa relación",
        "Implementa la herencia",
        "Aplica los cambios sugeridos",
        "Aplica esa relación",
        "Establece la relación entre ellas",
        "Pon esa composición en el diagrama",
        "Ejecuta lo propuesto",
        "Hazlo con la herencia recomendada",
    ]
    for prompt in mutation_prompts:
        intent = classify_agent_intent(prompt)
        assert intent.requires_mutation is True, f"Se esperaba requires_mutation=True para: {prompt}"
        assert has_direct_mutation_command(prompt) is True, f"Se esperaba has_direct_mutation_command=True para: {prompt}"
        assert requires_mutation(prompt) is True, f"Se esperaba requires_mutation=True para: {prompt}"

    read_only_prompts = [
        "¿En UML qué relación es la más adecuada si un Administrador es un tipo especializado de Usuario?",
        "¿Qué es una generalización?",
        "Explícame cómo funciona la herencia en UML",
        "No apliques esa generalización",
    ]
    for prompt in read_only_prompts:
        intent = classify_agent_intent(prompt)
        assert intent.requires_mutation is False, f"Se esperaba requires_mutation=False para: {prompt}"


@pytest.mark.anyio
async def test_dialog_extracts_recommendation_and_turn_interpreter_accepts():
    """Valida que extract_proposals_from_recent_exchanges y TurnInterpreter resuelvan la orden."""
    ex = RecentExchange(
        message_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        user_prompt="¿En UML qué relación es la más adecuada si un Administrador es un tipo especializado de Usuario?",
        assistant_response=(
            "La relación más adecuada en UML es Generalización (herencia)... "
            "Usuario es la superclase (base) y Administrador es la subclase (derivada)..."
        ),
        status="completed",
    )
    proposals = extract_proposals_from_recent_exchanges([ex])
    assert len(proposals) == 1, "Debe extraer 1 propuesta de la respuesta recomendada"
    prop = proposals[0]
    assert prop.action == "CREATE_RELATION"
    assert prop.slots["relation.type"] == "GENERALIZATION"
    assert prop.slots["relation.superclass"] == "Usuario"
    assert prop.slots["relation.subclass"] == "Administrador"

    # Verificar que el TurnInterpreter reconoce "Aplica esa generalización en las clases"
    interpreter = TurnInterpreter()
    state = DialogState(proposals=[prop])
    turn = await interpreter.interpret(
        user_message="Aplica esa generalización en las clases",
        dialog_state=state,
        context=None,
    )
    assert turn.user_act == "accept_proposal"

    # Verificar que DialogPolicy decide fulfill y genera la orden canónica
    policy = DialogPolicy()
    decision = policy.decide(turn=turn, state=state)
    assert decision.assistant_act == "fulfill"
    assert "Usuario" in (decision.resolved_request or "")
    assert "Administrador" in (decision.resolved_request or "")
    assert "herencia (generalización)" in (decision.resolved_request or "")


@pytest.mark.anyio
async def test_plan_executor_injects_conversation_history_into_messages():
    """Valida que PlanExecutor inyecte recent_turns en messages antes de ejecutar."""
    tool_call = AiToolCall(
        id="call-1",
        name="apply_diagram_changes",
        arguments={
            "actions": [
                {
                    "action_kind": "CREATE_RELATION",
                    "relation_type": "GENERALIZATION",
                    "source_class_id": str(uuid4()),
                    "target_class_id": str(uuid4()),
                }
            ]
        },
    )
    # Primero responde con un tool call, luego con la confirmación final
    provider = RecordingAiProvider(
        responses=[
            AiResult(text="", model_role=ModelRole.MAIN, model="mock", tool_calls=[tool_call]),
            AiResult(text="Se ha creado la relación de generalización exitosamente.", model_role=ModelRole.MAIN, model="mock", completed=True),
        ]
    )
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            AiToolDefinition(
                name="apply_diagram_changes",
                description="mutate",
                parameters={"type": "object", "properties": {"actions": {"type": "array"}}},
            ),
            lambda args, _progress: {"status": "applied", "applied_changes": [{"action_kind": "CREATE_RELATION"}]},
            mutating=True,
        )
    )
    executor = PlanExecutor(
        ai_provider=provider,
        tool_registry=registry,
    )

    recent_turns = [
        {
            "user": "¿En UML qué relación es la más adecuada si un Administrador es un tipo especializado de Usuario?",
            "assistant": "La relación más adecuada en UML es Generalización (herencia), donde Usuario es la superclase y Administrador es la subclase.",
        }
    ]
    context = AgentContext(
        user_id="user-1",
        project_id=uuid4(),
        prompt="Aplica esa generalización en las clases",
        instructions="Eres el asistente...",
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=1000,
        requires_compaction=False,
        recent_turns=recent_turns,
    )

    result = await executor.execute(context=context, plan=None)
    assert result.completed is True
    assert len(provider.requests) >= 1

    first_request = provider.requests[0]
    # Verificar que el historial fue inyectado
    history_found = False
    for msg in first_request.messages:
        if "Historial reciente de la conversación" in (msg.content or ""):
            history_found = True
            assert "¿En UML qué relación es la más adecuada" in msg.content
            assert "Generalización (herencia)" in msg.content
    assert history_found is True, "El historial conversacional debió ser inyectado en los mensajes del LLM"
