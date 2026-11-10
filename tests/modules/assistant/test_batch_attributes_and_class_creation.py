"""Pruebas unitarias para creación de atributos en lote y corrección de parada prematura."""

from __future__ import annotations

from uuid import UUID, uuid4
import pytest
from sqlmodel import select

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.services.context_builder import AgentContext
from app.modules.assistant.application.services.diagram.diagram_mutation_tools import (
    DiagramMutationTools,
)
from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
    validate_actions,
)
from app.modules.assistant.application.services.execution.plan_executor import (
    PlanExecutor,
    _has_pending_mutation_text,
)
from app.modules.assistant.application.services.execution.tool_registry import (
    RegisteredTool,
    ToolRegistry,
)
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def _make_action(kind: str, **kwargs) -> dict:
    return {
        "operation_id": f"op-{uuid4().hex[:8]}",
        "kind": kind,
        **kwargs,
    }


def _registry(session, project_id, user_id, event_bus=None):
    registry = ToolRegistry()
    DiagramMutationTools(
        session,
        SqlModelUnitOfWork(session, event_bus or InMemoryEventBus()),
        project_id=project_id,
        user_id=user_id,
    ).register(registry)
    return registry


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pruebas de Esquema y Validación para CREATE_CLASS con attributes
# ─────────────────────────────────────────────────────────────────────────────


def test_schema_create_class_with_valid_attributes():
    payload = {
        "actions": [
            _make_action(
                "CREATE_CLASS",
                name="Producto",
                attributes=[
                    {"name": "id", "data_type": "UUID"},
                    {"name": "nombre", "data_type": "TEXT", "nullable": False},
                    {"name": "precio", "data_type": "DECIMAL"},
                    {"name": "categoria_id"},
                ],
            )
        ]
    }
    normalized = validate_actions(payload)
    assert len(normalized) == 1
    action = normalized[0]
    assert action["kind"] == "CREATE_CLASS"
    assert action["name"] == "Producto"
    assert len(action["attributes"]) == 4
    assert action["attributes"][1]["name"] == "nombre"
    assert action["attributes"][1]["data_type"] == "TEXT"
    assert action["attributes"][1]["nullable"] is False


def test_schema_create_class_with_invalid_attributes_fails():
    # Atributo sin nombre
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_CLASS",
                    name="Producto",
                    attributes=[{"data_type": "TEXT"}],
                )
            ]
        })

    # Atributo con tipo inválido
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_CLASS",
                    name="Producto",
                    attributes=[{"name": "nombre", "data_type": "INVALID_TYPE"}],
                )
            ]
        })

    # Atributo con campo no permitido
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_CLASS",
                    name="Producto",
                    attributes=[{"name": "nombre", "is_primary_key": True}],
                )
            ]
        })

    # attributes no es lista
    with pytest.raises(AgentToolArgumentsException):
        validate_actions({
            "actions": [
                _make_action(
                    "CREATE_CLASS",
                    name="Producto",
                    attributes="nombre, precio",
                )
            ]
        })


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pruebas de Ejecución Atómica: CREATE_CLASS con attributes y filtrado PK/FK
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_class_with_attributes_creates_class_and_secondary_attributes(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    result = await registry.execute(
        "apply_diagram_changes",
        {
            "actions": [
                {
                    "operation_id": "create_producto",
                    "kind": "CREATE_CLASS",
                    "name": "Producto",
                    "attributes": [
                        {"name": "id", "data_type": "UUID"},
                        {"name": "nombre", "data_type": "TEXT"},
                        {"name": "precio", "data_type": "DECIMAL"},
                        {"name": "categoria_id", "data_type": "INTEGER"},
                    ],
                }
            ]
        },
    )

    assert result["status"] == "applied"
    action_res = result["results"][0]
    assert action_res["status"] == "applied"

    # Verificar derived_effects: PK ya materializada, FK ignorada
    effects = action_res.get("derived_effects", [])
    effect_types = [e["type"] for e in effects]
    assert "already_materialized" in effect_types
    assert "foreign_key_ignored" in effect_types

    # Verificar entidades en BD
    classes = session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.deleted_date.is_(None),
        )
    ).all()
    assert len(classes) == 1
    producto = classes[0]
    assert producto.name == "Producto"

    attributes = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == producto.id,
            DiagramAttributeModel.deleted_date.is_(None),
        )
    ).all()

    # Debe haber 3 atributos: PK (id), nombre (TEXT) y precio (DECIMAL).
    # categoria_id no debe haber sido creado como atributo ordinario.
    attr_names = [a.name for a in attributes]
    assert "id" in attr_names
    assert "nombre" in attr_names
    assert "precio" in attr_names
    assert "categoria_id" not in attr_names

    pk_attr = next(a for a in attributes if a.name == "id")
    assert pk_attr.is_primary_key is True

    nombre_attr = next(a for a in attributes if a.name == "nombre")
    assert nombre_attr.data_type == DiagramAttributeDataType.TEXT

    precio_attr = next(a for a in attributes if a.name == "precio")
    assert precio_attr.data_type == DiagramAttributeDataType.DECIMAL


# ─────────────────────────────────────────────────────────────────────────────
# 3. Creación de atributos en lote para clase existente
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_batch_create_attributes_on_existing_class(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    # 1. Crear clase vacía
    create_cls = await registry.execute(
        "apply_diagram_changes",
        {"actions": [{"operation_id": "c1", "kind": "CREATE_CLASS", "name": "Cliente"}]},
    )
    class_id = create_cls["results"][0]["entity_refs"][0]["id"]

    # 2. Añadir múltiples atributos en un solo batch
    add_attrs = await registry.execute(
        "apply_diagram_changes",
        {
            "actions": [
                {"operation_id": "a1", "kind": "CREATE_ATTRIBUTE", "class_id": class_id, "name": "nombre"},
                {"operation_id": "a2", "kind": "CREATE_ATTRIBUTE", "class_id": class_id, "name": "email"},
                {"operation_id": "a3", "kind": "CREATE_ATTRIBUTE", "class_id": class_id, "name": "telefono"},
            ]
        },
    )

    assert add_attrs["status"] == "applied"
    assert len(add_attrs["results"]) == 3
    assert all(r["status"] == "applied" for r in add_attrs["results"])

    attributes = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == UUID(class_id),
            DiagramAttributeModel.deleted_date.is_(None),
        )
    ).all()

    attr_names = {a.name for a in attributes}
    assert {"id", "nombre", "email", "telefono"} <= attr_names


# ─────────────────────────────────────────────────────────────────────────────
# 4. Detección y corrección de parada prematura en PlanExecutor
# ─────────────────────────────────────────────────────────────────────────────


def test_has_pending_mutation_text_detection():
    # Textos que indican parada prematura conversacional
    assert _has_pending_mutation_text(
        "Clase Producto creada con ID 4f3a970e. Procedo a añadir los atributos solicitados: id, nombre, precio y categoria_id."
    ) is True
    assert _has_pending_mutation_text(
        "A continuación voy a crear los atributos de la clase Producto."
    ) is True
    assert _has_pending_mutation_text(
        "Paso a añadir las columnas nombre y precio."
    ) is True
    assert _has_pending_mutation_text(
        "Ahora crearé la relación entre Producto y Categoria."
    ) is True

    # Textos finales que no son parada prematura
    assert _has_pending_mutation_text(
        "He creado la clase Producto con sus atributos nombre y precio exitosamente."
    ) is False
    assert _has_pending_mutation_text(
        "La clase Producto contiene 3 atributos y 1 relación."
    ) is False


class MockAiProviderSequence:
    def __init__(self, responses: list[AiResult]):
        self.responses = list(responses)
        self.recorded_requests = []

    async def complete(self, request):
        self.recorded_requests.append(request)
        return self.responses.pop(0)


@pytest.mark.anyio
async def test_plan_executor_nudges_model_on_premature_conversational_stop():
    registry = ToolRegistry()
    called_operations = []

    async def mock_handler(arguments, report=None):
        for act in arguments.get("actions", []):
            called_operations.append(act["kind"])
        return {
            "status": "applied",
            "results": [
                {
                    "operation_id": act["operation_id"],
                    "status": "applied",
                    "entity_refs": [{"type": "class", "id": str(uuid4())}],
                }
                for act in arguments.get("actions", [])
            ],
        }

    from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
        DIAGRAM_MUTATION_TOOL,
    )
    registry.register(
        RegisteredTool(
            DIAGRAM_MUTATION_TOOL,
            mock_handler,
            mutating=True,
        )
    )

    # Simular:
    # 1. Turno 1: Modelo llama a CREATE_CLASS
    # 2. Turno 2: Modelo devuelve texto "Procedo a añadir..." con 0 tool calls
    # 3. Turno 3: PlanExecutor inyecta corrección; modelo responde llamando a CREATE_ATTRIBUTE
    # 4. Turno 4: Modelo devuelve texto final "Todo completado"
    res1 = AiResult(
        text="",
        model_role=ModelRole.MAIN,
        model="qwen",
        tool_calls=[
            AiToolCall(
                id="call_1",
                name="apply_diagram_changes",
                arguments={"actions": [{"operation_id": "op1", "kind": "CREATE_CLASS", "name": "Producto"}]},
            )
        ],
    )
    res2 = AiResult(
        text="Clase Producto creada. Procedo a añadir los atributos nombre y precio.",
        model_role=ModelRole.MAIN,
        model="qwen",
        tool_calls=[],
    )
    res3 = AiResult(
        text="",
        model_role=ModelRole.MAIN,
        model="qwen",
        tool_calls=[
            AiToolCall(
                id="call_2",
                name="apply_diagram_changes",
                arguments={
                    "actions": [
                        {"operation_id": "op2", "kind": "CREATE_ATTRIBUTE", "class_id": str(uuid4()), "name": "nombre"},
                        {"operation_id": "op3", "kind": "CREATE_ATTRIBUTE", "class_id": str(uuid4()), "name": "precio"},
                    ]
                },
            )
        ],
    )
    res4 = AiResult(
        text="He creado la clase Producto con sus atributos nombre y precio exitosamente.",
        model_role=ModelRole.MAIN,
        model="qwen",
        tool_calls=[],
    )

    mock_ai = MockAiProviderSequence([res1, res2, res3, res4])
    executor = PlanExecutor(mock_ai, registry, fast_synthesis=True)

    ctx = AgentContext(
        user_id="user1",
        project_id=uuid4(),
        instructions="",
        prompt="Crea una clase Producto con nombre y precio",
        summary_context="",
        image_url=None,
        memory_id=None,
        estimated_memory_tokens=0,
        compaction_threshold=100,
        requires_compaction=False,
    )

    result = await executor.execute(ctx, plan=None)

    assert result.completed is True
    # Verificamos que el ejecutor ejecutó ambas llamadas
    assert "CREATE_CLASS" in called_operations
    assert "CREATE_ATTRIBUTE" in called_operations
    # Verificamos que se hicieron 4 llamadas al modelo (incluyendo el turno de corrección)
    assert len(mock_ai.recorded_requests) == 4
    # Verificamos que el mensaje correctivo fue inyectado en el turno 3
    req3_msgs = mock_ai.recorded_requests[2].messages
    last_user_msg = [m for m in req3_msgs if m.role == "user"][-1]
    assert "No emitas texto conversacional preliminar sobre acciones futuras" in last_user_msg.content
