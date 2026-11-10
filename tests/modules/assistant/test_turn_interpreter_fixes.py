"""Pruebas dedicadas para validar las correcciones en TurnInterpreter:
1. 'Crea las clases Pedido y Producto' no debe capturar 'las' como atributo.
2. Validar que _llm_interpret acepte slots estructurados (listas, dicts) sin lanzar ValueError.
3. Fallback no debe atrapar comandos de mutación en un marco activo con provide_slots vacíos.
4. Extracción de atributos explícitos e implícitos con clases destino.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.dialog.turn_interpreter import TurnInterpreter
from app.modules.assistant.domain.dialog.dialog_frame import DialogFrame, DialogState


@pytest.mark.anyio
async def test_multi_class_request_does_not_extract_las_as_attribute():
    """El mensaje 'Crea las clases Pedido (con fecha, total, estado) y Producto (con nombre, precio, stock)'
    no debe ser interpretado como CREATE_ATTRIBUTE con attribute.name='las'.
    """
    interpreter = TurnInterpreter()
    prompt = "Crea las clases Pedido (con fecha, total, estado) y Producto (con nombre, precio, stock)"
    
    # Deterministic parse directamente
    parsed = interpreter._try_deterministic_parse(
        clean=prompt,
        norm_text=prompt.casefold(),
        dialog_state=DialogState(),
    )
    # No debe capturar "las" como atributo
    if parsed is not None:
        assert parsed.proposed_action != "CREATE_ATTRIBUTE"
        assert parsed.slots.get("attribute.name") != "las"


@pytest.mark.anyio
async def test_simple_multi_class_request_does_not_match_attribute():
    """'Crea las clases Pedido y Producto' no debe capturar 'las' ni 'clases'."""
    interpreter = TurnInterpreter()
    prompt = "Crea las clases Pedido y Producto"
    
    parsed = interpreter._try_deterministic_parse(
        clean=prompt,
        norm_text=prompt.casefold(),
        dialog_state=DialogState(),
    )
    if parsed is not None:
        assert parsed.proposed_action != "CREATE_ATTRIBUTE"


@pytest.mark.anyio
async def test_llm_interpret_accepts_structured_slots_without_value_error():
    """Cuando el LLM devuelve slots con listas (como atributos de una clase),
    no debe lanzar ValueError('Los campos del análisis deben ser texto.').
    """
    mock_ai = Mock(spec=AiProvider)
    llm_payload = {
        "user_act": "new_request",
        "action": "CREATE_CLASS",
        "slots": {
            "class.name": "Pedido",
            "attributes": [
                {"name": "fecha"},
                {"name": "total"},
                {"name": "estado"},
            ],
        },
        "rationale": "Creación de clase Pedido con atributos",
    }
    mock_ai.complete = AsyncMock(
        return_value=AiResult(
            text=json.dumps(llm_payload),
            model_role=ModelRole.MAIN,
            model="qwen3.7-plus-2026-05-26",
        )
    )

    interpreter = TurnInterpreter(ai_provider=mock_ai)
    state = DialogState()
    frame = DialogFrame(id="f1", action="CREATE_ATTRIBUTE")
    state.add_frame(frame)

    result = await interpreter._llm_interpret(
        user_message="Crea las clases Pedido (con fecha, total, estado) y Producto (con nombre, precio, stock)",
        dialog_state=state,
        context=None,
    )

    assert result.user_act == "new_request"
    assert result.proposed_action == "CREATE_CLASS"
    assert result.slots["class.name"] == "Pedido"
    assert isinstance(result.slots["attributes"], list)
    assert len(result.slots["attributes"]) == 3


@pytest.mark.anyio
async def test_explicit_attribute_creation_still_works():
    """'Crea el atributo fecha' debe extraerse correctamente como atributo."""
    interpreter = TurnInterpreter()
    prompt = "Crea el atributo fecha"
    
    parsed = interpreter._try_deterministic_parse(
        clean=prompt,
        norm_text=prompt.casefold(),
        dialog_state=DialogState(),
    )
    assert parsed is not None
    assert parsed.proposed_action == "CREATE_ATTRIBUTE"
    assert parsed.slots.get("attribute.name") == "fecha"


@pytest.mark.anyio
async def test_attribute_with_target_class_still_works():
    """'Agrega email a la clase Usuario' debe extraerse con nombre y clase destino."""
    interpreter = TurnInterpreter()
    prompt = "Agrega email a la clase Usuario"
    
    parsed = interpreter._try_deterministic_parse(
        clean=prompt,
        norm_text=prompt.casefold(),
        dialog_state=DialogState(),
    )
    assert parsed is not None
    assert parsed.proposed_action == "CREATE_ATTRIBUTE"
    assert parsed.slots.get("attribute.name") == "email"
    assert parsed.slots.get("attribute.target_class") == "Usuario"


@pytest.mark.anyio
async def test_fallback_does_not_trap_mutation_in_active_frame():
    """Si hay un marco activo pero el usuario envía una orden de mutación clara
    y no hay LLM ni parseo determinista, el fallback debe ser new_request UNKNOWN,
    no provide_slots con slots vacíos.
    """
    interpreter = TurnInterpreter(ai_provider=None)
    state = DialogState()
    frame = DialogFrame(id="f1", action="CREATE_ATTRIBUTE")
    frame.set_slot("attribute.name", "las")
    state.add_frame(frame)

    turn = await interpreter.interpret(
        user_message="Crea las clases Pedido y Producto",
        dialog_state=state,
    )

    assert turn.user_act == "new_request"
    assert turn.proposed_action == "UNKNOWN"
