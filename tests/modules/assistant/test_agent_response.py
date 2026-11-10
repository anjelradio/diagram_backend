"""Pruebas de consistencia de estructura, orden y formato de respuestas del agente (US3)."""

from __future__ import annotations

import re
import pytest

from app.modules.assistant.application.services.execution.agent_response import (
    CommunicableFact,
    determine_response_type,
    extract_communicable_facts,
    format_deterministic_response,
    sanitize_markdown_response,
)
from tests.modules.assistant.fixtures.agent_response_cases import RESPONSE_TEST_CASES

_UUID_REGEX = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def test_consistent_mutation_structure_across_cases():
    """Dos solicitudes de mutación exitosas deben presentar la misma estructura y orden."""
    facts_a = [
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="Factura", action="created"),
        CommunicableFact(result_type="confirmed_change", entity_type="attribute", entity_name="total", action="created"),
    ]
    facts_b = [
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="Cliente", action="created"),
        CommunicableFact(result_type="confirmed_change", entity_type="attribute", entity_name="email", action="created"),
    ]

    resp_a = format_deterministic_response(facts_a, "mutation")
    resp_b = format_deterministic_response(facts_b, "mutation")

    # Ambas inician con el mismo encabezado cordial
    assert resp_a.startswith("¡Listo! He aplicado los siguientes cambios en el diagrama:")
    assert resp_b.startswith("¡Listo! He aplicado los siguientes cambios en el diagrama:")

    # Ambas presentan el resultado principal antes de detalles secundarios
    lines_a = [ln.strip() for ln in resp_a.splitlines() if ln.strip()]
    lines_b = [ln.strip() for ln in resp_b.splitlines() if ln.strip()]
    assert len(lines_a) == 3
    assert len(lines_b) == 3

    assert "Factura" in lines_a[1] and "total" in lines_a[2]
    assert "Cliente" in lines_b[1] and "email" in lines_b[2]

    # Ninguna expone UUIDs
    assert not _UUID_REGEX.search(resp_a)
    assert not _UUID_REGEX.search(resp_b)


def test_consistent_query_structure_and_no_mutation_success_noise():
    """Dos consultas distintas responden directamente a la pregunta sin encabezados de mutación ni UUIDs."""
    facts_q1 = [
        CommunicableFact(
            result_type="query_answer",
            entity_type="query",
            entity_name="Diagrama",
            action="answered",
            details="El diagrama tiene 3 clases: Cliente, Pedido y Producto.",
        )
    ]
    facts_q2 = [
        CommunicableFact(
            result_type="query_answer",
            entity_type="query",
            entity_name="Diagrama",
            action="answered",
            details="La clase Factura posee los atributos id, fecha y total.",
        )
    ]

    resp_q1 = format_deterministic_response(facts_q1, "query")
    resp_q2 = format_deterministic_response(facts_q2, "query")

    # Responden directamente sin inventar listas de cambios ni anunciar mutación
    assert "3 clases: Cliente, Pedido y Producto" in resp_q1
    assert "La clase Factura posee los atributos" in resp_q2
    assert "¡Listo! He aplicado" not in resp_q1
    assert "¡Listo! He aplicado" not in resp_q2
    assert "cambios aplicados" not in resp_q1.lower()
    assert "cambios aplicados" not in resp_q2.lower()

    # Sin UUIDs
    assert not _UUID_REGEX.search(resp_q1)
    assert not _UUID_REGEX.search(resp_q2)


def test_mutation_without_confirmed_changes_does_not_claim_success():
    """Si no hubo cambios confirmados, no se anuncia falsamente éxito de mutación."""
    empty_facts: list[CommunicableFact] = []
    resp = format_deterministic_response(empty_facts, "mutation")

    assert "Listo. No fue necesario realizar cambios en el diagrama." in resp
    assert "¡Listo! He aplicado los siguientes cambios" not in resp
    assert "- Se creó" not in resp
    assert "- Se modificó" not in resp


def test_mixed_response_clearly_separates_changes_and_query_answers():
    """Un resultado mixto separa nítidamente cambios confirmados y respuesta a la consulta."""
    facts = [
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="Proveedor", action="created"),
        CommunicableFact(
            result_type="query_answer",
            entity_type="query",
            entity_name="Diagrama",
            action="answered",
            details="El total de clases en el proyecto ahora es de 5.",
        ),
    ]

    resp = format_deterministic_response(facts, "mixed")

    assert "**Cambios confirmados:**" in resp
    assert "**Respuesta a tu consulta:**" in resp
    assert "Proveedor" in resp
    assert "total de clases en el proyecto ahora es de 5" in resp

    # El orden es claro: primero cambios confirmados, después respuesta a la consulta
    idx_cambios = resp.index("**Cambios confirmados:**")
    idx_consulta = resp.index("**Respuesta a tu consulta:**")
    assert idx_cambios < idx_consulta


def test_partial_failure_separates_applied_and_pending():
    """Fallo parcial separa cambios aplicados de tareas bloqueadas o fallidas."""
    facts = [
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="A", action="created"),
        CommunicableFact(result_type="failed", entity_type="task", entity_name="Crear B", action="failed", details="Error de sintaxis en B"),
        CommunicableFact(result_type="pending", entity_type="task", entity_name="Crear C", action="blocked", details="Bloqueada por fallo en B"),
    ]

    resp = format_deterministic_response(facts, "partial_failure")

    assert "**Cambios aplicados:**" in resp
    assert "**Tareas no completadas o pendientes:**" in resp
    assert "A" in resp
    assert "Error de sintaxis en B" in resp
    assert "Bloqueada por fallo en B" in resp


def test_cancelled_response_clarity():
    """Cancelación indica explícitamente el estado sin inventar cambios."""
    facts = [
        CommunicableFact(result_type="cancelled", entity_type="general", entity_name="Operación", action="cancelled"),
    ]
    resp = format_deterministic_response(facts, "cancelled")
    assert "cancelada" in resp.lower()
    assert "no se aplicaron cambios adicionales" in resp.lower()


def test_clarification_response_polite_structure():
    """Aclaración requerida estructura los puntos sin afirmar éxito."""
    facts = [
        CommunicableFact(
            result_type="clarification",
            entity_type="class",
            entity_name="Usuario",
            action="clarify",
            details="Existen dos clases llamadas Usuario: en auth y en billing.",
        )
    ]
    resp = format_deterministic_response(facts, "clarification")
    assert "aclara tu solicitud" in resp.lower()
    assert "Existen dos clases llamadas Usuario" in resp


def test_deduplication_of_confirmed_facts():
    """Si se reporta la misma entidad y acción dos veces, se evita duplicar la viñeta."""
    facts = [
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="Factura", action="created"),
        CommunicableFact(result_type="confirmed_change", entity_type="class", entity_name="Factura", action="created"),
    ]
    resp = format_deterministic_response(facts, "mutation")
    # Solo debe aparecer una vez
    assert resp.count("Factura") == 1


def test_sanitize_markdown_removes_private_thoughts_and_all_uuids():
    """sanitize_markdown_response elimina etiquetas de pensamiento y UUIDs en cualquier posición."""
    raw = (
        "<thought>Planificando la mutación: llamaré a diagram_class_tools.</thought>\n"
        "He creado la clase **Factura** (id: 11111111-2222-3333-4444-555555555555) y el atributo "
        "con id aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee con éxito.\n"
        "Identificador aislado: 99999999-8888-7777-6666-555555555555."
    )
    cleaned = sanitize_markdown_response(raw)

    assert "<thought>" not in cleaned
    assert "</thought>" not in cleaned
    assert "Planificando la mutación" not in cleaned
    assert not _UUID_REGEX.search(cleaned)
    assert "Factura" in cleaned


@pytest.mark.parametrize("case", RESPONSE_TEST_CASES, ids=lambda c: c.id)
def test_response_test_cases_corpus(case):
    """Verifica que todos los casos de prueba del corpus cumplen palabras esperadas y prohíben patrones no deseados."""
    facts = [
        CommunicableFact(
            result_type=f.result_type,
            entity_type=f.entity_type,
            entity_name=f.entity_name,
            action=f.action,
            details=f.details,
        )
        for f in case.facts
    ]

    resp = format_deterministic_response(facts, case.response_type)
    cleaned = sanitize_markdown_response(resp)

    # 1. Comprobar palabras clave esperadas
    for kw in case.expected_included_keywords:
        assert kw.lower() in cleaned.lower(), f"Caso {case.id}: '{kw}' no encontrado en:\n{cleaned}"

    # 2. Comprobar patrones prohibidos (ej. UUIDs)
    for forbidden in case.forbidden_patterns:
        match = re.search(forbidden, cleaned, re.IGNORECASE)
        assert match is None, f"Caso {case.id}: patrón prohibido '{forbidden}' encontrado en:\n{cleaned}"


def test_response_presentation_distinguishes_applied_and_pending_without_uuids():
    """La respuesta ante una ejecución parcial distingue claramente los cambios aplicados de los pendientes sin UUIDs."""
    facts = [
        CommunicableFact(
            result_type="confirmed_change",
            entity_type="class",
            entity_name="Pedido",
            action="created",
            details="Se creó clase Pedido (creada).",
        ),
        CommunicableFact(
            result_type="pending",
            entity_type="task",
            entity_name="Crear relación con Cliente",
            action="blocked",
            details="Crear relación con Cliente (pendiente de confirmación).",
        ),
    ]

    resp = format_deterministic_response(facts, "partial_failure")
    cleaned = sanitize_markdown_response(resp)

    assert "Cambios aplicados:" in cleaned
    assert "Pedido" in cleaned
    assert "pendientes" in cleaned.lower()
    assert "Cliente" in cleaned
    assert not _UUID_REGEX.search(cleaned)
    # No debe afirmar éxito total
    assert "¡Listo!" not in cleaned


def test_response_presentation_blocked_does_not_leak_internal_ids():
    """Un error con UUIDs en la descripción de tareas pendientes se sanitiza completamente."""
    facts = [
        CommunicableFact(
            result_type="pending",
            entity_type="task",
            entity_name="Tarea",
            action="blocked",
            details="Bloqueada por fallo en 12345678-1234-1234-1234-123456789abc al crear Factura.",
        ),
    ]

    resp = format_deterministic_response(facts, "partial_failure")
    cleaned = sanitize_markdown_response(resp)

    assert not _UUID_REGEX.search(cleaned)
    assert "Factura" in cleaned


def test_format_plan_execution_response_partial_with_counts_and_safe_reasons():
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
    from app.modules.assistant.application.services.execution.agent_response import (
        format_plan_execution_response,
    )

    plan = ExecutionPlan.create(
        goal="Crear clases y atributos",
        tasks=[
            {
                "id": "t1",
                "objective": "Añadir atributo nombre a Producto",
                "status": "completed",
            },
            {
                "id": "t2",
                "objective": "Añadir precio a Venta",
                "status": "failed",
                "error_code": "class_not_found",
                "failure_reason": "la clase requerida ya no está disponible",
            },
        ],
    )
    plan.operation_ledger = [
        {
            "operation_id": "op-1",
            "task_id": "t1",
            "status": "applied",
            "action_kind": "CREATE_ATTRIBUTE",
            "entity_refs": [{"type": "attribute", "id": "attr-1", "name": "nombre"}],
        },
        {
            "operation_id": "op-2",
            "task_id": "t2",
            "status": "rejected",
            "action_kind": "CREATE_ATTRIBUTE",
            "entity_refs": [{"type": "attribute", "id": "attr-2", "name": "precio"}],
        },
    ]
    plan.recompute_overall_status()
    assert plan.status == "partial"

    resp = format_plan_execution_response(plan)

    # 1. Conteo explícito
    assert "1 tarea" in resp
    assert "1 pendiente" in resp or "1 no completada" in resp

    # 2. Cambios confirmados del ledger
    assert "nombre" in resp
    # La operación rechazada jamás se afirma como cambio aplicado
    assert "precio" not in resp.split("Cambios aplicados")[1].split("Tareas no completadas")[0]

    # 3. Motivo seguro presente en la sección no completada
    assert "la clase requerida ya no está disponible" in resp

    # 4. Orientación accionable
    assert "revisar el diagrama" in resp.lower() or "revisa el diagrama" in resp.lower()

    # 5. Sin UUIDs
    assert not _UUID_REGEX.search(resp)


def test_format_plan_execution_response_never_claims_unapplied_operations():
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
    from app.modules.assistant.application.services.execution.agent_response import (
        format_plan_execution_response,
    )

    plan = ExecutionPlan.create(
        goal="Plan sin cambios confirmados",
        tasks=[
            {
                "id": "t1",
                "objective": "Modificar algo inexistente",
                "status": "failed",
                "error_code": "class_not_found",
                "failure_reason": "la clase requerida ya no está disponible",
            }
        ],
    )
    plan.operation_ledger = [
        {
            "operation_id": "op-1",
            "task_id": "t1",
            "status": "rejected",
            "entity_refs": [{"type": "class", "id": "id-leak", "name": "Fantasma"}],
        }
    ]
    plan.recompute_overall_status()

    resp = format_plan_execution_response(plan)

    assert "Cambios aplicados" not in resp
    assert "¡Listo!" not in resp
    assert "Fantasma" not in resp
    assert "la clase requerida ya no está disponible" in resp


def test_sanitize_markdown_response_removes_all_uuid_variants():
    """Valida que sanitize_markdown_response elimine UUIDs con backticks, paréntesis y prefijos técnicos."""
    raw = (
        "He creado la clase Pedido (ID: `067f7faa-3e2d-40c6-bbd6-56409fe7e475`) "
        "y la clase Producto con ID `16cb030a-dfd7-497d-aa53-841dc412cf88`. "
        "También la relación con id: cc819904-8025-4523-95c0-111122223333 "
        "y clase puente (`12345678-1234-1234-1234-123456789abc`)."
    )
    sanitized = sanitize_markdown_response(raw)

    # Ningún UUID debe sobrevivir
    assert not _UUID_REGEX.search(sanitized)
    assert "`" not in sanitized
    assert "067f7faa" not in sanitized
    assert "16cb030a" not in sanitized
    assert "cc819904" not in sanitized
    assert "12345678" not in sanitized

    # No deben quedar paréntesis vacíos ni basura
    assert "(ID: )" not in sanitized
    assert "()" not in sanitized
    assert "(ID:" not in sanitized

    # El contenido semántico se mantiene limpio
    assert "He creado la clase Pedido" in sanitized
    assert "y la clase Producto" in sanitized


def test_format_plan_execution_response_proactive_class_creation():
    """Valida que si una tarea no completada falló por class_not_found, se sugiera crearla."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
    from app.modules.assistant.application.services.execution.agent_response import format_plan_execution_response

    plan = ExecutionPlan.create(
        goal="Agregar atributo en Usuario",
        tasks=[
            {
                "id": "t1",
                "objective": "Crear atributo en Usuario",
                "status": "failed",
                "error_code": "class_not_found",
                "target_class": "Usuario",
                "failure_reason": "la clase requerida ya no está disponible",
            }
        ],
    )
    plan.recompute_overall_status()
    resp = format_plan_execution_response(plan)
    assert "¿Deseas que cree la clase **Usuario**" in resp
    assert "(puedes responder 'sí' o 'créala')" in resp


