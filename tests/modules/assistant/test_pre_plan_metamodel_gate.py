"""Pruebas dedicadas para la Compuerta Pre-Flight de Metamodelo UML y Resiliencia de Herramientas."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.assistant.application.services.intent.metamodel_gate import (
    MetamodelGateKind,
    check_metamodel_gate,
    is_conceptual_question,
)
from app.modules.assistant.application.services.diagram.diagram_tool_schemas import (
    validate_actions,
)
from app.modules.assistant.domain.entities.agent_message import AgentMessage
from app.modules.assistant.domain.entities.agent_continuation import ContinuationOutcome, ContinuationPurpose
from app.modules.assistant.domain.exceptions import AgentToolArgumentsException
from app.modules.assistant.application.use_cases.process_agent_message import (
    ProcessAgentMessageUseCase,
)


def test_isolated_fk_detection():
    # Caso 1: FK en clase específica
    d1 = check_metamodel_gate("Crea una llave foránea cliente_id en la clase Factura")
    assert d1 is not None
    assert d1.kind == MetamodelGateKind.ISOLATED_FK
    assert d1.target_class == "Factura"
    assert d1.requires_input is True
    assert "no se agregan manualmente como atributos" in d1.explanation
    assert "**Factura**" in d1.explanation
    assert "|" not in d1.explanation  # Cero tablas markdown

    # Caso 2: FK genérica
    d2 = check_metamodel_gate("Agrega una clave foránea")
    assert d2 is not None
    assert d2.kind == MetamodelGateKind.ISOLATED_FK
    assert d2.requires_input is True
    assert "¿Entre cuáles dos clases deseas crear la relación" in d2.explanation

    # Caso 3: FK con clase destino explícita
    d3 = check_metamodel_gate("Crea una fk en Pedido para relacionar con Cliente")
    assert d3 is not None
    assert d3.kind == MetamodelGateKind.ISOLATED_FK
    assert d3.target_class == "Pedido"
    assert d3.related_class == "Cliente"
    assert "con **Cliente**" in d3.explanation


def test_isolated_pk_detection():
    # Caso 1: PK en clase específica
    d1 = check_metamodel_gate("Crea una llave primaria en Factura")
    assert d1 is not None
    assert d1.kind == MetamodelGateKind.ISOLATED_PK
    assert d1.target_class == "Factura"
    assert d1.requires_input is False
    assert "id: UUID" in d1.explanation
    assert "|" not in d1.explanation

    # Caso 2: PK genérica
    d2 = check_metamodel_gate("Agrega una primary key")
    assert d2 is not None
    assert d2.kind == MetamodelGateKind.ISOLATED_PK
    assert d2.requires_input is False


def test_ambiguous_relation_detection():
    # Caso 1: Diagrama con 3 o más clases
    d1 = check_metamodel_gate("Relaciona las clases", existing_classes=["Cliente", "Factura", "Producto"])
    assert d1 is not None
    assert d1.kind == MetamodelGateKind.AMBIGUOUS_RELATION
    assert d1.requires_input is True
    assert "¿Cuáles dos clases del diagrama deseas relacionar?" in d1.explanation

    # Caso 2: Diagrama con exactamente 2 clases
    d2 = check_metamodel_gate("conecta las clases", existing_classes=["Usuario", "Rol"])
    assert d2 is not None
    assert d2.kind == MetamodelGateKind.AMBIGUOUS_RELATION
    assert d2.requires_input is True
    assert "**Usuario**" in d2.explanation
    assert "**Rol**" in d2.explanation

    # Caso 3: "haz una relación" sin extremos
    d3 = check_metamodel_gate("haz una relación", existing_classes=[])
    assert d3 is not None
    assert d3.kind == MetamodelGateKind.AMBIGUOUS_RELATION


def test_normal_and_conceptual_requests_not_intercepted():
    # Acciones directas normales pasan sin intercepción
    assert check_metamodel_gate("Crea la clase Factura con total y fecha") is None
    assert check_metamodel_gate("Crea una relación entre Cliente y Factura de 1 a N") is None
    assert check_metamodel_gate("Elimina la clase Proveedor") is None

    # Preguntas conceptuales pasan sin intercepción para respuesta conceptual
    assert check_metamodel_gate("¿Qué es una llave foránea?") is None
    assert check_metamodel_gate("¿Cómo funcionan las llaves primarias?") is None
    assert check_metamodel_gate("¿Por qué las clases tienen id UUID?") is None


def test_validate_actions_resilience():
    # 1. Sin operation_id y con nulls en attributes/position
    payload = {
        "actions": [
            {
                "kind": "CREATE_CLASS",
                "name": "Proveedor",
                "position": None,
                "attributes": None,
            }
        ]
    }
    normalized = validate_actions(payload)
    assert len(normalized) == 1
    assert normalized[0]["kind"] == "CREATE_CLASS"
    assert normalized[0]["name"] == "Proveedor"
    assert normalized[0]["operation_id"] == "op_1"
    assert "position" not in normalized[0]
    assert "attributes" not in normalized[0]

    # 2. Con attributes array que incluye nullable: None y clave extra nula
    payload2 = {
        "actions": [
            {
                "kind": "CREATE_CLASS",
                "name": "Proveedor",
                "attributes": [
                    {"name": "nombre", "data_type": "TEXT", "nullable": None, "extra_null": None},
                    {"name": "telefono", "data_type": "TEXT"},
                ],
            }
        ]
    }
    normalized2 = validate_actions(payload2)
    assert len(normalized2[0]["attributes"]) == 2
    assert normalized2[0]["attributes"][0]["name"] == "nombre"
    assert "nullable" not in normalized2[0]["attributes"][0]
    assert "extra_null" not in normalized2[0]["attributes"][0]

    # 3. Operaciones con IDs repetidos explícitos deben fallar según contrato
    payload3 = {
        "actions": [
            {"operation_id": "op-dup", "kind": "CREATE_CLASS", "name": "A"},
            {"operation_id": "op-dup", "kind": "CREATE_CLASS", "name": "B"},
        ]
    }
    with pytest.raises(AgentToolArgumentsException):
        validate_actions(payload3)


def test_pre_plan_metamodel_gate_use_case_fk_interception():
    # Mock de repositorios y dependencias del caso de uso
    msg = AgentMessage(
        id=uuid4(),
        project_id=uuid4(),
        user_id="user-123",
        prompt="Crea una llave foránea cliente_id en la clase Factura",
    )
    repo_cont = MagicMock()
    uow = MagicMock()

    use_case = ProcessAgentMessageUseCase(
        message_repository=MagicMock(),
        memory_repository=MagicMock(),
        project_access_policy=MagicMock(),
        context_builder=MagicMock(),
        orchestrator=MagicMock(),
        uow=uow,
        continuation_repository=repo_cont,
        class_provider=lambda pid: {"Factura": "id-factura", "Cliente": "id-cliente"},
    )

    ctx, immediate = use_case._check_pre_plan_metamodel_gate(msg)
    assert ctx is None
    assert immediate is not None
    assert immediate.completed is True
    assert immediate.metadata.get("gate_kind") == "ISOLATED_FK"
    assert "no se agregan manualmente como atributos" in immediate.text
    # Se debe haber guardado una continuación esperando input
    assert repo_cont.save.called
    saved_cont = repo_cont.save.call_args[0][0]
    assert saved_cont.outcome == ContinuationOutcome.AWAITING_INPUT
    assert saved_cont.purpose == ContinuationPurpose.CLARIFICATION
    assert uow.commit.called
