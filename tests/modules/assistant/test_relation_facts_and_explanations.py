"""Pruebas para verificar la correcta extracción de hechos en relaciones,
la exclusión de atributos derivados automáticos (FK) y la preservación de
explicaciones cuando una entidad no existe."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.execution.agent_response import (
    _extract_clean_name,
    extract_communicable_facts,
    format_deterministic_response,
    format_plan_execution_response,
)
from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan


def test_extract_clean_name_extracts_relation_pair_from_objective():
    """_extract_clean_name debe extraer 'Factura ↔ DetalleFactura' en lugar de toda la oración."""
    ref = {"type": "relation", "id": str(uuid4())}
    task = {"objective": "Crear una relación entre la clase Factura y la clase DetalleFactura."}

    name = _extract_clean_name(ref, task)
    assert name == "Factura ↔ DetalleFactura"
    assert "Crear una relación" not in name


def test_extract_clean_name_uses_ref_name_when_available():
    """Si ref tiene name, debe usarse directamente."""
    ref = {"type": "relation", "id": str(uuid4()), "name": "Usuario ↔ Administrador"}
    task = {"objective": "Conectar con herencia donde Usuario sea el padre."}

    name = _extract_clean_name(ref, task)
    assert name == "Usuario ↔ Administrador"


def test_extract_communicable_facts_filters_derived_fk_attributes():
    """extract_communicable_facts no debe anunciar llaves foráneas automáticas como atributos creados."""
    rel_id = str(uuid4())
    fk_attr_id = str(uuid4())
    task_id = "rel-1"

    task = {
        "id": task_id,
        "objective": "Crear una relación entre la clase Factura y la clase DetalleFactura.",
        "kind": "mutation",
        "status": "completed",
    }
    ledger_entries = [
        {
            "operation_id": "op-1",
            "task_id": task_id,
            "action_kind": "CREATE_RELATION",
            "status": "applied",
            "entity_refs": [
                {"type": "relation", "id": rel_id, "name": "Factura ↔ DetalleFactura"},
                {"type": "attribute", "id": fk_attr_id},
            ],
            "derived_effects": [
                {"type": "attribute", "id": fk_attr_id},
            ],
        }
    ]

    facts = extract_communicable_facts(
        ledger_entries=ledger_entries,
        tasks=[task],
    )

    # Solo debe existir 1 hecho confirmado (la relación), no 2
    assert len(facts) == 1
    assert facts[0].entity_type in {"relation", "relación"}
    assert facts[0].entity_name == "Factura ↔ DetalleFactura"

    resp = format_deterministic_response(facts, "mutation")
    assert "- Se creó relación **Factura ↔ DetalleFactura** (creada)." in resp
    assert "atributo" not in resp.lower()


def test_format_plan_execution_response_filters_derived_fk_attributes():
    """format_plan_execution_response tampoco debe listar llaves foráneas derivadas."""
    rel_id = str(uuid4())
    fk_attr_id = str(uuid4())
    task_id = "rel-1"

    plan = ExecutionPlan.create(
        goal="Crear relación",
        tasks=[
            {
                "id": task_id,
                "objective": "Crear una relación entre Factura y DetalleFactura",
                "kind": "mutation",
                "status": "completed",
                "depends_on": [],
            }
        ],
    )
    plan.operation_ledger = [
        {
            "operation_id": "op-1",
            "task_id": task_id,
            "action_kind": "CREATE_RELATION",
            "status": "applied",
            "entity_refs": [
                {"type": "relation", "id": rel_id, "name": "Factura ↔ DetalleFactura"},
                {"type": "attribute", "id": fk_attr_id},
            ],
            "derived_effects": [
                {"type": "attribute", "id": fk_attr_id},
            ],
        }
    ]

    resp = format_plan_execution_response(plan)
    assert "Factura ↔ DetalleFactura" in resp
    assert "atributo" not in resp.lower()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_plan_executor_preserves_explanation_when_mutation_unconfirmed():
    """Si una tarea de mutación no ejecuta herramientas porque una clase no existe,
    debe conservar la explicación del LLM en failure_reason."""
    from app.modules.assistant.application.services.execution.plan_executor import (
        PlanExecutor,
    )
    from app.modules.assistant.application.services.execution.tool_registry import (
        ToolRegistry,
    )

    ai_provider = MagicMock()
    # El LLM devuelve un texto explicando que la clase Cliente no existe
    ai_provider.complete = AsyncMock(
        return_value=AiResult(
            text="La clase Cliente no existe en el diagrama. ¿Deseas que la cree primero?",
            model_role=ModelRole.MAIN,
            model="mock",
            tool_calls=(),
            completed=True,
        )
    )

    tool_registry = MagicMock(spec=ToolRegistry)
    tool_registry.definitions_for_task.return_value = ()

    executor = PlanExecutor(
        ai_provider=ai_provider,
        tool_registry=tool_registry,
    )

    plan = ExecutionPlan.create(
        goal="Relacionar Cliente con Factura",
        tasks=[
            {
                "id": "rel-task",
                "objective": "Crear relación entre Cliente y Factura",
                "kind": "mutation",
                "depends_on": [],
            }
        ],
    )

    context = AgentContext(
        user_id="user-1",
        project_id=uuid4(),
        instructions="",
        prompt="Relaciona Cliente con Factura",
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=1000,
        requires_compaction=False,
        effective_request="Relacionar Cliente con Factura",
        authorized_mode="execute",
    )

    result = await executor.execute(context, plan)

    # La tarea debe marcarse como fallida pero con failure_reason preservado
    task = plan.tasks[0]
    assert task["status"] == "failed"
    assert "La clase Cliente no existe en el diagrama" in task.get("failure_reason", "")
