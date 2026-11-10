"""Pruebas exhaustivas para los escenarios de optimización del asistente conversacional.

Cubre:
1. Bucle multi-turno de aclaración con acumulación parcial de datos y una sola pregunta agrupada.
2. Comandos "Dos en Uno" (sugerencia + mutación en diagrama o Notion).
3. Pre-flight check temprano para proyectos sin integración de Notion configurada o inicializada.
4. Resolución flexible de tareas por ordinal/índice/título y cierre automático a 'Done' sin formato erróneo.
5. Compatibilidad de alcance visual (visual_scope) con herramientas de mutación ajenas al diagrama.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.application.services.intent.semantic_intent_router import (
    SemanticCategory,
    SemanticIntentRouter,
)
from app.modules.assistant.application.services.planning.agent_intent import (
    classify_agent_intent,
    requires_mutation,
    requires_plan,
)
from app.modules.assistant.application.services.execution.agent_response import (
    CommunicableFact,
    extract_communicable_facts,
    format_deterministic_response,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationOutcome,
    ContinuationPurpose,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionTaskRecord,
)
from app.modules.integrations.domain.enums.notion_task_priority import NotionTaskPriority
from app.modules.integrations.domain.enums.notion_task_status import NotionTaskStatus
from app.modules.assistant.application.services.integrations.notion_agent_tools import (
    NotionAgentTools,
)


# ── 1. Bucle Multi-Turno de Falta de Información y Acumulación Parcial ───────

@pytest.mark.anyio
async def test_multiturn_clarification_loop_accumulates_partial_info():
    """Verifica que el enrutador agrupe los datos faltantes y acumule respuestas parciales."""
    router = SemanticIntentRouter(ai_provider=None)

    # Turno 1: Usuario pide crear un atributo sin especificar clase ni nombre
    decision_1 = await router.route_turn(
        prompt="crea un atributo",
        recent_turns=(),
        existing_classes={"Factura": "uuid-fac"},
        active_continuation=None,
    )
    assert decision_1.category == SemanticCategory.NEEDS_MORE_CONTEXT
    assert "target_class" in decision_1.missing_info
    assert "attribute_name" in decision_1.missing_info
    # Debe ser una única pregunta agrupando los datos faltantes con viñetas
    q1 = decision_1.clarification_question or ""
    assert "¿En qué clase" in q1 and "¿Qué nombre" in q1

    # Simular guardado de la continuación activa del turno 1
    cont_turn_1 = AgentContinuation.create(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-1",
        root_message_id=uuid4(),
        source_plan_message_id=uuid4(),
        effective_request=decision_1.resolved_goal,
        outcome=ContinuationOutcome.AWAITING_INPUT,
        purpose=ContinuationPurpose.CLARIFICATION,
        missing_fields=tuple({"field": f} for f in decision_1.missing_info),
    )

    # Turno 2: El usuario solo proporciona la clase (respuesta parcial)
    decision_2 = await router.route_turn(
        prompt="en la clase Factura",
        recent_turns=(),
        existing_classes={"Factura": "uuid-fac"},
        active_continuation=cont_turn_1,
    )
    assert decision_2.category == SemanticCategory.NEEDS_MORE_CONTEXT
    assert "attribute_name" in decision_2.missing_info
    assert "target_class" not in decision_2.missing_info
    assert "Factura" in decision_2.resolved_goal
    assert "nombre" in (decision_2.clarification_question or "").lower()
    assert "factura" in (decision_2.clarification_question or "").lower()

    # Simular actualización de la continuación para el turno 2
    cont_turn_2 = AgentContinuation.create(
        id=uuid4(),
        project_id=cont_turn_1.project_id,
        user_id="user-1",
        root_message_id=cont_turn_1.root_message_id,
        source_plan_message_id=uuid4(),
        effective_request=decision_2.resolved_goal,
        outcome=ContinuationOutcome.AWAITING_INPUT,
        purpose=ContinuationPurpose.CLARIFICATION,
        missing_fields=tuple({"field": f} for f in decision_2.missing_info),
    )

    # Turno 3: El usuario proporciona el nombre faltante
    decision_3 = await router.route_turn(
        prompt="total",
        recent_turns=(),
        existing_classes={"Factura": "uuid-fac"},
        active_continuation=cont_turn_2,
    )
    assert decision_3.category == SemanticCategory.CONTINUATION_OR_ANAPHORA
    assert decision_3.requires_mutation is True
    assert "Factura" in decision_3.resolved_goal
    assert "total" in decision_3.resolved_goal


# ── 2. Casos "Dos en Uno" (Sugerencia + Orden de Mutación) ───────────────────

def test_two_in_one_suggestion_plus_mutation_intent():
    """Verifica que 'Dos en Uno' active mutación y planificación para entregar la sugerencia y aplicarla."""
    prompt_diagram = "¿Qué atributos me sugieres para Producto? Dame la sugerencia y colócalos en la clase Producto"
    intent_diagram = classify_agent_intent(prompt_diagram)
    assert intent_diagram.requires_mutation is True
    assert requires_plan(prompt_diagram) is True

    prompt_rel = "¿Qué relación me recomiendas entre Curso y Estudiante? Créala"
    intent_rel = classify_agent_intent(prompt_rel)
    assert intent_rel.requires_mutation is True
    assert requires_plan(prompt_rel) is True


def test_pure_hypothetical_question_is_not_mutation():
    """Verifica que una pregunta puramente hipotética sin orden imperativa no active mutaciones."""
    prompt = "¿debería crear una clase para los pagos?"
    assert requires_mutation(prompt) is False
    assert requires_plan(prompt) is False


# ── 3. Resolución Flexible de Tareas de Notion (Ordinales, Números, Títulos) ───

@pytest.mark.anyio
async def test_notion_agent_tools_resolve_task_by_index_and_ordinal():
    """Verifica que update_task y delete_task resuelvan task_id numéricos, ordinales o por título."""
    mock_notion_provider = MagicMock()
    mock_task_1 = NotionTaskRecord(
        task_id="uuid-task-1111-2222-3333-444455556666",
        title="Crear diagrama de usuarios",
        description="Modelar tabla usuarios",
        status=NotionTaskStatus.PENDING,
        priority=NotionTaskPriority.HIGH,
        assignee_name="Anjel",
        due_date=None,
        url="https://notion.so/task1",
    )
    mock_task_2 = NotionTaskRecord(
        task_id="uuid-task-7777-8888-9999-aaaabbbbcccc",
        title="Configurar pagos",
        description="Integrar stripe",
        status=NotionTaskStatus.PENDING,
        priority=NotionTaskPriority.MEDIUM,
        assignee_name="Anjel",
        due_date=None,
        url="https://notion.so/task2",
    )

    mock_notion_provider.list_tasks.return_value = [mock_task_1, mock_task_2]
    mock_notion_provider.get_task.side_effect = lambda api_key, task_id: (
        mock_task_1 if task_id == mock_task_1.task_id else (
            mock_task_2 if task_id == mock_task_2.task_id else None
        )
    )
    mock_notion_provider.update_task.return_value = mock_task_1

    mock_crypto = MagicMock()
    mock_crypto.decrypt.return_value = "decrypted-key"

    mock_repo = MagicMock()
    mock_integration = MagicMock()
    mock_integration.encrypted_api_key = "enc-key"
    mock_integration.external_database_id = "db-123"
    mock_repo.find_by_project_and_provider.return_value = mock_integration

    tools = NotionAgentTools(
        project_id=uuid4(),
        current_user_name="Anjel",
        integration_repository=mock_repo,
        crypto_service=mock_crypto,
        notion_provider=mock_notion_provider,
    )

    # 1. Resolver por ordinal "primera"
    res_1 = await tools._update_task({"task_id": "primera", "status": "Done"})
    assert res_1["status"] == "applied"
    assert res_1["task"]["task_id"] == mock_task_1.task_id

    # 2. Resolver por número "2"
    mock_notion_provider.update_task.return_value = mock_task_2
    res_2 = await tools._update_task({"task_id": "2", "status": "Done"})
    assert res_2["status"] == "applied"
    assert res_2["task"]["task_id"] == mock_task_2.task_id

    # 3. Resolver por título "pagos"
    res_3 = await tools._update_task({"task_id": "Configurar pagos", "status": "Done"})
    assert res_3["status"] == "applied"
    assert res_3["task"]["task_id"] == mock_task_2.task_id


# ── 4. Formateo Limpio de Hechos Confirmados para Notion ──────────────────────

def test_communicable_facts_notion_closure_formatting():
    """Verifica que cerrar o crear tareas en Notion genere un resumen limpio sin decir 'elemento Notion'."""
    facts = extract_communicable_facts(
        tasks=[
            {
                "id": "close-notion-task-1",
                "objective": "Marcar la tarea 'Modelado de Clientes' como Done en Notion",
                "kind": "mutation",
                "status": "completed",
                "notion_task_id": "uuid-123",
            }
        ]
    )

    assert len(facts) == 1
    assert facts[0].entity_type == "notion_task"
    assert facts[0].entity_name == "Modelado de Clientes"
    assert facts[0].action == "updated"

    rendered = format_deterministic_response(facts, "mutation")
    assert "elemento Notion" not in rendered
    assert "Se marcó la tarea de Notion **Modelado de Clientes** como Done." in rendered


def test_communicable_facts_notion_creation_formatting():
    """Verifica que la creación de una tarea en Notion se formatee como tarea de Notion."""
    facts = extract_communicable_facts(
        tasks=[
            {
                "id": "create-notion-task",
                "objective": "Crear tarea 'Atributos de Producto' en Notion",
                "kind": "mutation",
                "status": "completed",
                "notion_task_id": "uuid-456",
            }
        ]
    )
    rendered = format_deterministic_response(facts, "mutation")
    assert "elemento Notion" not in rendered
    assert "Se creó la tarea de Notion **Atributos de Producto**." in rendered


# ── 5. Compatibilidad de Alcance Visual con Herramientas Ajenas al Diagrama ───

@pytest.mark.anyio
async def test_tool_registry_allows_notion_mutations_with_visual_scope():
    """Verifica que visual_scope no bloquee herramientas de mutación externas (como Notion)."""
    registry = ToolRegistry()

    async def dummy_handler(args, report=None):
        return {"status": "applied", "task_id": "notion-123"}

    # Registrar herramienta de mutación sin visual_scope_validator (como create_notion_task)
    notion_tool = AiToolDefinition(
        name="create_notion_task",
        description="Crea una tarea en Notion",
        parameters={"type": "object"},
    )
    registry.register(
        RegisteredTool(
            definition=notion_tool,
            handler=dummy_handler,
            mutating=True,
            visual_scope_validator=None,
        )
    )

    # Ejecutar con visual_scope activo (por ejemplo, tras procesar una imagen adjunta)
    visual_scope = {"classes": ["Producto"], "attributes": [], "relations": []}
    result = await registry.execute(
        "create_notion_task",
        {"title": "Tarea desde imagen", "description": "Detalles"},
        visual_scope=visual_scope,
    )

    assert result["status"] == "applied"
    assert result["task_id"] == "notion-123"


# ── 6. Pre-flight Check y Reconocimiento de Ordinales de Notion ──────────────

from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
    _is_notion_related_prompt,
    _is_single_notion_task_execution_request,
)


def test_is_notion_related_prompt_detection():
    """Verifica detección precisa de peticiones dirigidas a Notion vs entidades de diagrama."""
    assert _is_notion_related_prompt("Crea una tarea en Notion para revisar Factura") is True
    assert _is_notion_related_prompt("Lista mis tareas pendientes de Notion") is True
    assert _is_notion_related_prompt("muestra los pendientes de notion") is True
    assert _is_notion_related_prompt("crea una clase Factura") is False
    assert _is_notion_related_prompt("crea un atributo total") is False


def test_is_single_notion_task_execution_with_ordinals():
    """Verifica reconocimiento de referencias ordinales tras listado previo de tareas."""
    # Sin turnos previos ni contexto, 'haz la primera' no es una tarea
    assert _is_single_notion_task_execution_request("haz la primera") is False

    # Con turnos previos que contienen notion_tasks en caché
    recent_turns = [
        {
            "user": "lista mis tareas de Notion",
            "assistant": "Aquí tienes tus tareas",
            "notion_tasks": [
                {"task_id": "uuid-1", "title": "Crear Factura"},
                {"task_id": "uuid-2", "title": "Crear Detalle"},
            ],
        }
    ]
    assert _is_single_notion_task_execution_request("implementa la primera", recent_turns=recent_turns) is True
    assert _is_single_notion_task_execution_request("haz la segunda", recent_turns=recent_turns) is True
    assert _is_single_notion_task_execution_request("ejecuta la 1", recent_turns=recent_turns) is True
    assert _is_single_notion_task_execution_request("aplica la última", recent_turns=recent_turns) is True


def test_notion_preflight_check_unconfigured_and_uninitialized():
    """Verifica respuesta inmediata cuando Notion no está configurado o no inicializado."""
    mock_repo = MagicMock()
    mock_provider = MagicMock()
    mock_crypto = MagicMock()

    use_case = ProcessAgentMessageUseCase(
        message_repository=MagicMock(),
        memory_repository=None,
        project_access_policy=MagicMock(),
        context_builder=MagicMock(),
        orchestrator=MagicMock(),
        uow=MagicMock(),
        integration_repository=mock_repo,
        notion_provider=mock_provider,
        crypto_service=mock_crypto,
    )

    proj_id = uuid4()

    # Caso 1: Integración no existe o no tiene API key
    mock_repo.find_by_project_and_provider.return_value = None
    res_1 = use_case._check_notion_integration_readiness(proj_id)
    assert res_1 is not None
    assert "primero debes activarlo e ingresar tu API Key" in res_1.text

    # Caso 2: Integración existe con API key pero no está inicializada
    mock_integration = MagicMock()
    mock_integration.encrypted_api_key = "encrypted"
    mock_integration.is_initialized = False
    mock_integration.external_database_id = None
    mock_repo.find_by_project_and_provider.return_value = mock_integration

    res_2 = use_case._check_notion_integration_readiness(proj_id)
    assert res_2 is not None
    assert "aún no ha sido inicializada en este proyecto" in res_2.text

    # Caso 3: Integración completa y lista
    mock_integration.is_initialized = True
    mock_integration.external_database_id = "db-ready-123"
    res_3 = use_case._check_notion_integration_readiness(proj_id)
    assert res_3 is None


def test_execution_plan_validates_notion_operation_ledger_and_metadata():
    """Verifica que ExecutionPlan valide correctamente entity_refs de Notion (con 'type') y metadata."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    plan = ExecutionPlan.create(
        goal="Crear una tarea en Notion con los atributos sugeridos para Administrador",
        tasks=[
            {
                "id": "direct",
                "objective": "Crear tarea en Notion",
                "kind": "mutation",
                "status": "completed",
            }
        ],
    )
    plan.metadata["notion_tasks_snapshot"] = [{"task_id": "t-1", "title": "Atributos Administrador"}]
    plan.operation_ledger.append(
        {
            "operation_id": "op-create_notion_task-12345678",
            "task_id": "direct",
            "tool_name": "create_notion_task",
            "action_kind": "CREATE_NOTION_TASK",
            "status": "applied",
            "entity_refs": [
                {
                    "type": "notion_task",
                    "kind": "NOTION_TASK",
                    "id": "414fff1f-5472-81cf-a885-f71cc1a4ef92",
                    "name": "Atributos sugeridos para la clase Administrador",
                }
            ],
        }
    )

    serialized = plan.to_dict()
    assert serialized["metadata"]["notion_tasks_snapshot"][0]["task_id"] == "t-1"
    restored = ExecutionPlan.from_dict(serialized)
    assert restored.operation_ledger[0]["entity_refs"][0]["type"] == "notion_task"
    assert restored.metadata["notion_tasks_snapshot"][0]["title"] == "Atributos Administrador"


