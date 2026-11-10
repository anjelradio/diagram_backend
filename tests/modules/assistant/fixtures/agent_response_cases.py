"""Fixtures de casos de respuesta para probar la redacción de hechos comunicables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ResponseType = Literal["mutation", "query", "mixed", "partial_failure", "cancelled", "clarification"]


@dataclass(frozen=True, slots=True)
class CommunicableFact:
    result_type: str  # confirmed_change | query_answer | pending | failed | cancelled | clarification
    entity_type: str  # class | attribute | relation | query | general
    entity_name: str
    action: str  # created | updated | deleted | answered | blocked | failed | cancelled | clarify
    details: str = ""


@dataclass(frozen=True, slots=True)
class ResponseTestCase:
    id: str
    response_type: ResponseType
    prompt: str
    facts: list[CommunicableFact]
    expected_included_keywords: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)  # e.g., regex/patterns for UUIDs


RESPONSE_TEST_CASES: list[ResponseTestCase] = [
    # 1. Mutación confirmada (creación)
    ResponseTestCase(
        id="mutation_create_classes_attributes",
        response_type="mutation",
        prompt="crea una clase Papanatas con atributo Arcoiris",
        facts=[
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="class",
                entity_name="Papanatas",
                action="created",
                details="Clase Papanatas",
            ),
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="attribute",
                entity_name="Arcoiris",
                action="created",
                details="Atributo Arcoiris en clase Papanatas",
            ),
        ],
        expected_included_keywords=["Papanatas", "Arcoiris", "creada", "atributo"],
        forbidden_patterns=["[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"],
    ),
    # 2. Mutación confirmada (edición y eliminación)
    ResponseTestCase(
        id="mutation_update_delete",
        response_type="mutation",
        prompt="actualiza la clase Factura y elimina Borrador",
        facts=[
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="class",
                entity_name="Factura",
                action="updated",
                details="Clase Factura actualizada",
            ),
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="class",
                entity_name="Borrador",
                action="deleted",
                details="Clase Borrador eliminada",
            ),
        ],
        expected_included_keywords=["Factura", "Borrador", "actualizada", "eliminada"],
        forbidden_patterns=["[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"],
    ),
    # 3. Consulta sin cambios
    ResponseTestCase(
        id="query_only",
        response_type="query",
        prompt="¿qué clases hay en el diagrama?",
        facts=[
            CommunicableFact(
                result_type="query_answer",
                entity_type="query",
                entity_name="Diagrama",
                action="answered",
                details="El diagrama contiene las clases Cliente, Factura y Pedido.",
            ),
        ],
        expected_included_keywords=["Cliente", "Factura", "Pedido"],
        forbidden_patterns=[
            "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "cambios confirmados",
            "se creó",
            "se modificó",
        ],
    ),
    # 4. Solicitud mixta (cambio + consulta)
    ResponseTestCase(
        id="mixed_mutation_and_query",
        response_type="mixed",
        prompt="crea una clase Proveedor y dime cuántas clases hay",
        facts=[
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="class",
                entity_name="Proveedor",
                action="created",
                details="Clase Proveedor",
            ),
            CommunicableFact(
                result_type="query_answer",
                entity_type="query",
                entity_name="Diagrama",
                action="answered",
                details="Ahora hay un total de 4 clases en el proyecto.",
            ),
        ],
        expected_included_keywords=["Proveedor", "4 clases"],
        forbidden_patterns=["[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"],
    ),
    # 5. Fallo parcial
    ResponseTestCase(
        id="partial_failure",
        response_type="partial_failure",
        prompt="crea A, crea B con atributo x que falla",
        facts=[
            CommunicableFact(
                result_type="confirmed_change",
                entity_type="class",
                entity_name="A",
                action="created",
                details="Clase A",
            ),
            CommunicableFact(
                result_type="failed",
                entity_type="class",
                entity_name="B",
                action="failed",
                details="Error al crear clase B",
            ),
            CommunicableFact(
                result_type="pending",
                entity_type="attribute",
                entity_name="x",
                action="blocked",
                details="Atributo x bloqueado",
            ),
        ],
        expected_included_keywords=["A", "B", "pendiente"],
        forbidden_patterns=["[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"],
    ),
    # 6. Cancelación
    ResponseTestCase(
        id="cancelled_execution",
        response_type="cancelled",
        prompt="crea una clase Compleja",
        facts=[
            CommunicableFact(
                result_type="cancelled",
                entity_type="general",
                entity_name="Operación",
                action="cancelled",
                details="Operación cancelada por el usuario antes de aplicar cambios.",
            ),
        ],
        expected_included_keywords=["cancelad"],
        forbidden_patterns=[
            "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "cambios confirmados",
        ],
    ),
    # 7. Aclaración requerida
    ResponseTestCase(
        id="clarification_required",
        response_type="clarification",
        prompt="actualiza la clase Usuario",
        facts=[
            CommunicableFact(
                result_type="clarification",
                entity_type="class",
                entity_name="Usuario",
                action="clarify",
                details="Existen múltiples clases llamadas Usuario. Por favor indica a cuál te refieres.",
            ),
        ],
        expected_included_keywords=["Usuario", "aclarar"],
        forbidden_patterns=["[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"],
    ),
]
