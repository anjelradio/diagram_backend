"""Pruebas dedicadas para validar las correcciones a los 4 casos reportados por el usuario:
1. Retención de contexto tras guía pedagógica de PK y creación de atributos subsecuente con typos.
2. Recuperación y aceptación fluida de propuestas en respuestas consultivas.
3. Batching atómico de atributos para clases existentes.
4. Turnos compuestos: abandono/cancelación del hilo previo y ejecución de nueva orden en el mismo turno.
"""

from __future__ import annotations

from uuid import uuid4
import pytest

from app.modules.assistant.application.ports.readers.agent_conversation_reader import (
    RecentExchange,
)
from app.modules.assistant.application.services.dialog.dialog_manager import (
    DialogManager,
    extract_proposals_from_recent_exchanges,
)
from app.modules.assistant.application.services.dialog.dialog_policy import DialogPolicy
from app.modules.assistant.application.services.dialog.turn_interpreter import TurnInterpreter
from app.modules.assistant.application.services.dialog.turn_signals import extract_turn_signals
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState, Proposal
from app.modules.assistant.domain.entities.agent_continuation import (
    AgentContinuation,
    ContinuationCloseReason,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage, AgentMessageStatus
from tests.modules.assistant.test_dialog_conversations import InMemoryContinuationRepository


@pytest.mark.anyio
async def test_bug1_context_retention_after_pk_guidance_and_typo_attribute():
    """Caso 1 (Prueba 2):
    Turno 1: 'Agrega una llave primaria id_producto a Producto'
             -> Se responde pedagógicamente y se inicializa marco CREATE_ATTRIBUTE para Producto.
    Turno 2: 'agrea descripcion' (con error ortográfico 'agrea')
             -> Se captura attribute.name='descripcion' en Producto y se resuelve a fulfill.
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    # 1. Turno de petición de PK manual
    turn1 = await interpreter.interpret(
        user_message="Agrega una llave primaria id_producto a Producto",
        dialog_state=state,
    )
    assert turn1.user_act == "request_primary_key_guidance"
    assert turn1.slots.get("class.name") == "Producto"

    decision1 = policy.decide(turn=turn1, state=state)
    assert decision1.assistant_act == "disambiguate"
    assert "ya cuenta automáticamente con su llave primaria (`id`)" in decision1.assistant_message
    assert "¿Deseas agregar algún otro atributo ordinario" in decision1.assistant_message
    # El marco activo de CREATE_ATTRIBUTE debe haberse fijado con Producto
    assert state.active_frame is not None
    assert state.active_frame.action == "CREATE_ATTRIBUTE"
    assert state.active_frame.slots["attribute.target_class"].value == "Producto"

    # 2. Turno subsecuente con typo "agrea descripcion"
    turn2 = await interpreter.interpret(
        user_message="agrea descripcion",
        dialog_state=state,
    )
    assert turn2.user_act == "provide_slots"
    assert turn2.slots.get("attribute.name") == "descripcion"

    # 3. La política ingiere el slot y como ya tiene Producto y descripcion, pasa a fulfill
    decision2 = policy.decide(turn=turn2, state=state)
    assert decision2.assistant_act == "fulfill"
    assert "Producto" in decision2.resolved_request
    assert "descripcion" in decision2.resolved_request


@pytest.mark.anyio
async def test_bug1_context_resolution_when_class_is_provided_subsequently():
    """Caso 1 variante:
    Marco activo esperando la clase: 'En qué clase deseas agregar descripcion?'
    Usuario responde: 'a la clase producto' o 'producto'
    -> Debe capturar attribute.target_class='producto' y cumplir.
    """
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState()

    frame = DialogFrame(id="attr_frame", action="CREATE_ATTRIBUTE")
    frame.set_slot("attribute.name", "descripcion")
    state.add_frame(frame)

    turn = await interpreter.interpret(
        user_message="a la clase producto",
        dialog_state=state,
    )
    assert turn.user_act == "provide_slots"
    assert turn.slots.get("attribute.target_class").casefold() == "producto"

    decision = policy.decide(turn=turn, state=state)
    assert decision.assistant_act == "fulfill"
    assert "descripcion" in decision.resolved_request


@pytest.mark.anyio
async def test_bug2_consult_proposal_recovery_and_acceptance():
    """Caso 2 (Prueba 5):
    La IA respondió recomendando atributos y sugirió:
    'Si un Usuario pertenece a un Cliente... se recomienda crear una relación entre ambas clases. ¿Quieres que cree esta relación?'
    Usuario: 'Si'
    -> extract_proposals_from_recent_exchanges detecta la propuesta y el intérprete la acepta.
    """
    assistant_text = (
        "Te recomiendo los siguientes atributos para cada clase:\n"
        "Cliente: nombre, apellido, email, telefono, direccion, fecha_registro\n"
        "Usuario: username, password, email, rol, activo, ultimo_acceso\n\n"
        "Nota de modelado:\n"
        "Si un Usuario pertenece a un Cliente (por ejemplo, en un sistema donde los clientes tienen cuentas de usuario), "
        "se recomienda crear una relación entre ambas clases.\n"
        "¿Quieres que cree esta relación?"
    )
    recent = RecentExchange(
        message_id=uuid4(),
        created_at=None,
        user_prompt="Qué atributos me recomiendas para la clase cliente y para la clase usuario?",
        assistant_response=assistant_text,
        confirmed_operations=(),
        status="completed",
        outcome=None,
        kind=None,
        assistant_act=None,  # No era consult_with_proposal formalmente
        is_superseded=False,
    )

    proposals = extract_proposals_from_recent_exchanges([recent])
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.action == "CREATE_RELATION"
    assert prop.slots["relation.type"] == "ASSOCIATION"
    assert "Cliente" in (prop.slots["relation.source_class"], prop.slots["relation.target_class"])
    assert "Usuario" in (prop.slots["relation.source_class"], prop.slots["relation.target_class"])
    assert prop.slots["relation.name"] == "pertenece"

    # Al ingresar "Si" con esta propuesta en el diálogo:
    interpreter = TurnInterpreter()
    policy = DialogPolicy()
    state = DialogState(proposals=[prop])

    turn = await interpreter.interpret(
        user_message="Si",
        dialog_state=state,
    )
    assert turn.user_act == "accept_proposal"

    decision = policy.decide(turn=turn, state=state)
    assert decision.assistant_act == "fulfill"
    assert "Cliente" in decision.resolved_request
    assert "Usuario" in decision.resolved_request


@pytest.mark.anyio
async def test_bug4_compound_turn_abandon_and_execute_new_request():
    """Caso 4 (Prueba 7):
    'Olvídate de eso y mejor crea una clase Proveedor con nombre y telefono'
    -> Debe interpretarse como cambio de objetivo (topic_change / new_request),
       con raw_message='crea una clase Proveedor con nombre y telefono',
       cerrando la continuación previa y procediendo con pass_through/ejecución.
    """
    signals = extract_turn_signals("Olvídate de eso y mejor crea una clase Proveedor con nombre y telefono")
    # No debe considerarse declinación pura porque contiene la orden imperativa secundaria
    assert signals.is_decline is False

    interpreter = TurnInterpreter()
    turn = await interpreter.interpret(
        user_message="Olvídate de eso y mejor crea una clase Proveedor con nombre y telefono",
        dialog_state=DialogState(),
    )
    assert turn.user_act == "new_request"
    assert turn.thread_effect == "topic_change"
    assert "crea una clase Proveedor" in turn.raw_message

    # Verificar que el DialogManager cierra el hilo previo y emite pass_through
    project_id = uuid4()
    repo = InMemoryContinuationRepository()
    old_cont = AgentContinuation.create(
        id=uuid4(),
        project_id=project_id,
        user_id="u1",
        root_message_id=uuid4(),
        effective_request="Petición anterior pendiente",
    )
    repo.save(old_cont)

    manager = DialogManager(continuation_repository=repo)
    result = await manager.handle_turn(
        message=AgentMessage(
            id=uuid4(),
            project_id=project_id,
            user_id="u1",
            prompt="Olvídate de eso y mejor crea una clase Proveedor con nombre y telefono",
            status=AgentMessageStatus.RUNNING,
        )
    )

    assert result.status == "pass_through"
    assert "crea una clase Proveedor" in result.effective_request
    # La continuación anterior debe haberse cerrado por cambio de tema
    stored = repo.find_by_id(old_cont.id)
    assert stored.close_reason == ContinuationCloseReason.TOPIC_CHANGE


def test_bug3_batch_attribute_directives():
    """Caso 3 (Prueba 6):
    Verifica que las directrices de ejecución exijan estrictamente la creación
    en lote (batch) de atributos para clases existentes y prohíban llamadas uno por uno.
    """
    from app.modules.assistant.application.services.prompting.prompt_catalog import (
        create_default_prompt_catalog,
    )
    catalog = create_default_prompt_catalog()
    exec_policy = catalog["phase_execution"]
    assert "DEBES enviar todas las acciones `CREATE_ATTRIBUTE` juntas" in exec_policy.text
    assert "PROHIBIDO crear atributos uno por uno" in exec_policy.text

    from app.modules.assistant.application.services.prompting.legacy_prompts import TOOL_PROMPT
    assert "DEBES enviar todas las acciones `CREATE_ATTRIBUTE` juntas" in TOOL_PROMPT
    assert "NUNCA crees atributos uno por uno" in TOOL_PROMPT


def test_structural_relation_with_name_is_normalized_In_schema_and_tools():
    """Verifica que una relación estructural (ej. COMPOSITION) con 'name' no falle por InvalidDiagramRelationNameException."""
    from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
        validate_actions,
    )

    src_id = str(uuid4())
    tgt_id = str(uuid4())
    normalized = validate_actions(
        {
            "actions": [
                {
                    "operation_id": "op_comp",
                    "kind": "CREATE_RELATION",
                    "relation_type": "COMPOSITION",
                    "source_class_id": src_id,
                    "target_class_id": tgt_id,
                    "name": "contiene",
                }
            ]
        }
    )
    assert len(normalized) == 1
    assert normalized[0]["relation_type"] == "COMPOSITION"
    assert "name" not in normalized[0]


def test_extract_inline_mutation_tool_call_from_markdown_json_block():
    """Verifica que si el modelo emite un bloque ```json {"actions": [...]} ``` sin tool_calls nativo, se extraiga la llamada."""
    from app.modules.assistant.application.services.execution.plan_executor import (
        _extract_inline_mutation_tool_call,
    )

    raw_text = (
        "Voy a crear la clase **Cliente** con sus atributos: nombre, email y teléfono.\n\n"
        "```json\n"
        "{\n"
        '  "actions": [\n'
        "    {\n"
        '      "operation_id": "create_cliente_class",\n'
        '      "kind": "CREATE_CLASS",\n'
        '      "name": "Cliente",\n'
        '      "attributes": [\n'
        '        {"name": "nombre", "data_type": "TEXT"}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "```"
    )
    call = _extract_inline_mutation_tool_call(raw_text)
    assert call is not None
    assert call.name == "apply_diagram_changes"
    assert call.arguments["actions"][0]["kind"] == "CREATE_CLASS"
    assert call.arguments["actions"][0]["name"] == "Cliente"


def test_format_plan_execution_response_includes_created_classes_in_partial_summary():
    """Verifica que las clases creadas aparezcan siempre en 'Cambios aplicados' ante un resultado parcial."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
    from app.modules.assistant.application.services.execution.agent_response import (
        format_plan_execution_response,
    )

    plan = ExecutionPlan.create(
        goal="Crear sistema de ventas",
        tasks=[
            {"id": "create-producto", "objective": "Crear la clase Producto con sus atributos", "status": "completed"},
            {"id": "create-cliente", "objective": "Crear la clase Cliente con sus atributos", "status": "failed", "error_code": "missing_expected_operations"},
        ],
    )
    plan.operation_ledger = [
        {
            "operation_id": "op-prod",
            "task_id": "create-producto",
            "action_kind": "CREATE_CLASS",
            "target_name": "Producto",
            "status": "applied",
            "entity_refs": [
                {"type": "class", "id": str(uuid4()), "name": "Producto"},
                {"type": "attribute", "id": str(uuid4())},
            ],
        }
    ]
    plan.recompute_overall_status()
    response = format_plan_execution_response(plan)
    assert "**Cambios aplicados:**" in response
    assert "Se creó clase **Producto** (creada)." in response

