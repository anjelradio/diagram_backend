"""Corpus de aceptación para continuidad conversacional (SC-001 a SC-004).

Incluye:
- 10 casos de aclaración interactiva.
- 10 casos de reanudación parcial sin duplicación.
- Casos adversos para evaluar robustez y límites de seguridad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class ClarificationAcceptanceCase:
    case_id: str
    description: str
    initial_request: str
    critical_missing: list[dict[str, Any]]
    follow_up_input: str
    expected_resolved_facts: list[dict[str, Any]]
    expected_remaining_critical: list[str]
    success_criteria: str  # "SC-001" | "SC-003"


@dataclass(frozen=True, slots=True)
class PartialResumptionAcceptanceCase:
    case_id: str
    description: str
    initial_request: str
    prior_ledger: list[dict[str, Any]]
    user_prompt: str
    expected_residual_operations: list[str]
    forbidden_duplicated_operations: list[str]
    success_criteria: str  # "SC-002"


@dataclass(frozen=True, slots=True)
class AdverseAcceptanceCase:
    case_id: str
    description: str
    scenario: str  # "unreconciled_uncertain", "invalid_permission", "entity_deleted", "yes_with_missing_fields"
    initial_request: str
    prior_ledger: list[dict[str, Any]]
    user_prompt: str
    expected_outcome: str  # "blocked", "stopped", "re_ask", "rejected"
    success_criteria: str  # "SC-003" | "SC-004"


# --- 10 Casos de Aclaración ---
CLARIFICATION_ACCEPTANCE_CASES: list[ClarificationAcceptanceCase] = [
    ClarificationAcceptanceCase(
        case_id="clarify-01-relation-cardinality",
        description="Relación asociativa sin cardinalidades",
        initial_request="Relaciona Cliente y Pedido",
        critical_missing=[{"key": "relation.endpoint_cardinalities", "critical": True}],
        follow_up_input="1 a muchos",
        expected_resolved_facts=[{"key": "relation.source_cardinality", "value": "1"}, {"key": "relation.target_cardinality", "value": "0..*"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-02-attribute-missing-class",
        description="Atributo sin especificar la clase objetivo",
        initial_request="Agrega el atributo saldo",
        critical_missing=[{"key": "attribute.target_class", "critical": True}],
        follow_up_input="en la clase CuentaBancaria",
        expected_resolved_facts=[{"key": "attribute.target_class", "value": "CuentaBancaria"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-03-inheritance-direction",
        description="Herencia sin especificar cuál es la superclase",
        initial_request="Crea una herencia entre Empleado y Gerente",
        critical_missing=[{"key": "generalization.super_class", "critical": True}],
        follow_up_input="Empleado es la clase padre",
        expected_resolved_facts=[{"key": "generalization.super_class", "value": "Empleado"}, {"key": "generalization.sub_class", "value": "Gerente"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-04-composition-whole-part",
        description="Composición sin identificar todo y parte",
        initial_request="Composición entre Factura y LíneaFactura",
        critical_missing=[{"key": "composition.whole_class", "critical": True}],
        follow_up_input="Factura contiene las líneas",
        expected_resolved_facts=[{"key": "composition.whole_class", "value": "Factura"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-05-deletion-confirmation",
        description="Confirmación requerida para eliminar entidad existente",
        initial_request="Elimina la clase HistorialAuditoria",
        critical_missing=[{"key": "confirmation.explicit_delete", "critical": True}],
        follow_up_input="Sí, confirmo el borrado",
        expected_resolved_facts=[{"key": "confirmation.explicit_delete", "value": True}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-06-rename-target",
        description="Renombrado sin especificar nombre nuevo",
        initial_request="Renombra la clase Usuario",
        critical_missing=[{"key": "class.new_name", "critical": True}],
        follow_up_input="Quiero que se llame CuentaUsuario",
        expected_resolved_facts=[{"key": "class.new_name", "value": "CuentaUsuario"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-07-attribute-rename-name",
        description="Renombrado de atributo sin nombre nuevo",
        initial_request="Renombra el atributo total de Factura",
        critical_missing=[{"key": "attribute.new_name", "critical": True}],
        follow_up_input="Cámbialo a importeTotal",
        expected_resolved_facts=[{"key": "attribute.new_name", "value": "importeTotal"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-08-aggregation-container",
        description="Agregación sin clase agregadora",
        initial_request="Agregación entre Universidad y Departamento",
        critical_missing=[{"key": "aggregation.aggregate_class", "critical": True}],
        follow_up_input="Universidad es el contenedor",
        expected_resolved_facts=[{"key": "aggregation.aggregate_class", "value": "Universidad"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-09-relation-cardinality-bounds",
        description="Cardinalidad indicada como 'muchos a muchos'",
        initial_request="Relaciona Estudiante con Curso",
        critical_missing=[{"key": "relation.endpoint_cardinalities", "critical": True}],
        follow_up_input="0..* en ambos lados",
        expected_resolved_facts=[{"key": "relation.source_cardinality", "value": "0..*"}, {"key": "relation.target_cardinality", "value": "0..*"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
    ClarificationAcceptanceCase(
        case_id="clarify-10-visual-ambiguous-class-selection",
        description="Aclaración visual con selección de clase ambigua",
        initial_request="Interpreta el diagrama adjunto",
        critical_missing=[{"key": "visual.selected_class_id", "critical": True}],
        follow_up_input="Usa la clase con ID c1-usuario",
        expected_resolved_facts=[{"key": "visual.selected_class_id", "value": "c1-usuario"}],
        expected_remaining_critical=[],
        success_criteria="SC-001",
    ),
]


# --- 10 Casos de Reanudación Parcial ---
def _make_ledger_case(
    case_id: str,
    description: str,
    initial_request: str,
    applied_op_id: str,
    applied_action: str,
    remaining_op_id: str,
    remaining_action: str,
) -> PartialResumptionAcceptanceCase:
    return PartialResumptionAcceptanceCase(
        case_id=case_id,
        description=description,
        initial_request=initial_request,
        prior_ledger=[
            {
                "operation_id": applied_op_id,
                "action_kind": applied_action,
                "status": "applied",
                "summary": f"Operación aplicada {applied_op_id}",
            },
            {
                "operation_id": remaining_op_id,
                "action_kind": remaining_action,
                "status": "failed",
                "summary": f"Operación pendiente {remaining_op_id}",
            },
        ],
        user_prompt="sí, continúa",
        expected_residual_operations=[remaining_op_id],
        forbidden_duplicated_operations=[applied_op_id],
        success_criteria="SC-002",
    )


PARTIAL_RESUMPTION_ACCEPTANCE_CASES: list[PartialResumptionAcceptanceCase] = [
    _make_ledger_case("partial-01-two-classes", "Crear 2 clases, 1 aplicada y 1 pendiente", "Crea Producto y Stock", "op-c1", "CREATE_CLASS", "op-c2", "CREATE_CLASS"),
    _make_ledger_case("partial-02-class-and-attr", "Crear clase aplicada y atributo pendiente", "Crea Usuario con email", "op-c3", "CREATE_CLASS", "op-a1", "CREATE_ATTRIBUTE"),
    _make_ledger_case("partial-03-two-attributes", "Crear 2 atributos, 1 aplicado y 1 pendiente", "Agrega código y precio a Producto", "op-a2", "CREATE_ATTRIBUTE", "op-a3", "CREATE_ATTRIBUTE"),
    _make_ledger_case("partial-04-class-and-relation", "Crear clase aplicada y relación pendiente", "Crea Carrito y relación con Cliente", "op-c4", "CREATE_CLASS", "op-r1", "CREATE_RELATION"),
    _make_ledger_case("partial-05-rename-and-move", "Renombrar aplicado y mover pendiente", "Renombra Factura y muévela al centro", "op-rn1", "RENAME_CLASS", "op-mv1", "MOVE_CLASS"),
    _make_ledger_case("partial-06-two-relations", "Dos relaciones, 1 aplicada y 1 pendiente", "Relaciona Pedido con Cliente y con Pago", "op-r2", "CREATE_RELATION", "op-r3", "CREATE_RELATION"),
    _make_ledger_case("partial-07-multiple-attrs", "Tres atributos: 2 aplicados y 1 pendiente", "Agrega id, nombre y fecha", "op-a4", "CREATE_ATTRIBUTE", "op-a5", "CREATE_ATTRIBUTE"),
    _make_ledger_case("partial-08-generalization-and-attr", "Herencia aplicada y atributo en subclase pendiente", "Herencia Empleado->Gerente con bono", "op-g1", "CREATE_RELATION", "op-a6", "CREATE_ATTRIBUTE"),
    _make_ledger_case("partial-09-delete-and-create", "Borrado aplicado y creación pendiente", "Elimina Temp y crea Final", "op-d1", "DELETE_CLASS", "op-c5", "CREATE_CLASS"),
    _make_ledger_case("partial-10-composition-and-rename", "Composición aplicada y renombrado pendiente", "Composición y renombra componente", "op-cp1", "CREATE_RELATION", "op-rn2", "RENAME_CLASS"),
]


# --- Casos Adversos (SC-003 y SC-004) ---
ADVERSE_ACCEPTANCE_CASES: list[AdverseAcceptanceCase] = [
    AdverseAcceptanceCase(
        case_id="adverse-01-uncertain-unreconciled",
        description="Operación incierta no reconciliada detiene reintento automático",
        scenario="unreconciled_uncertain",
        initial_request="Crear relación compleja",
        prior_ledger=[
            {"operation_id": "op-u1", "action_kind": "CREATE_RELATION", "status": "uncertain", "summary": "Estado incierto por timeout"}
        ],
        user_prompt="sí, continúa",
        expected_outcome="blocked",
        success_criteria="SC-003",
    ),
    AdverseAcceptanceCase(
        case_id="adverse-02-yes-with-missing-fields",
        description="Respuesta 'sí' no rellena campos críticos ausentes",
        scenario="yes_with_missing_fields",
        initial_request="Relaciona Factura con Detalle",
        prior_ledger=[],
        user_prompt="sí",
        expected_outcome="re_ask",
        success_criteria="SC-003",
    ),
    AdverseAcceptanceCase(
        case_id="adverse-03-revoked-permission",
        description="Usuario sin permisos de lectura/escritura al reanudar",
        scenario="invalid_permission",
        initial_request="Crear clase en proyecto restringido",
        prior_ledger=[],
        user_prompt="procede",
        expected_outcome="rejected",
        success_criteria="SC-004",
    ),
    AdverseAcceptanceCase(
        case_id="adverse-04-entity-deleted-by-collaborator",
        description="Entidad eliminada por otro usuario antes de reanudar plan",
        scenario="entity_deleted",
        initial_request="Agregar atributo a clase eliminada",
        prior_ledger=[
            {"operation_id": "op-p1", "action_kind": "CREATE_CLASS", "status": "applied", "summary": "Creación inicial"}
        ],
        user_prompt="continúa",
        expected_outcome="stopped",
        success_criteria="SC-004",
    ),
]
