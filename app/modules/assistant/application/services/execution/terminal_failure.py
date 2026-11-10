"""Contrato, clasificación y formato local de fallos terminales de dominio.

Cumple con FR-001 a FR-008, SC-002, SC-004, SC-005, y T003-T004:
- Representación inmutable de fallos terminales por conflictos de dominio.
- Mapeo determinista de excepciones de negocio del módulo de diagramas.
- Saneamiento riguroso de identificadores y exclusión de detalles internos/UUIDs.
- Formateo de respuestas Markdown predefinidas sin inferencias adicionales de IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from app.modules.diagram.domain.exceptions import (
    BridgeClassCannotBeDeletedDirectlyException,
    DiagramAgentLockedException,
    DiagramAttributeIdConflictException,
    DiagramAttributeNotFoundException,
    DiagramClassIdConflictException,
    DiagramClassNameAlreadyExistsException,
    DiagramClassNotFoundException,
    DiagramRelationIdConflictException,
    DiagramRelationNotFoundException,
    DiagramRelationSelfReferenceException,
    DiagramWriteForbiddenException,
    DuplicateGeneralizationException,
    ForeignKeyCannotBeDeletedException,
    ForeignKeyCannotBeModifiedException,
    ForeignKeyCannotBeRepositionedException,
    InvalidAttributePositionException,
    InvalidDiagramAttributeNameException,
    InvalidDiagramClassNameException,
    InvalidDiagramCoordinatesException,
    InvalidDiagramRelationCardinalityException,
    InvalidDiagramRelationHandleException,
    InvalidDiagramRelationMaterializationException,
    InvalidDiagramRelationNameException,
    NonAssociativeRelationNameCannotBeModifiedException,
    PrimaryKeyCannotBeDeletedException,
    PrimaryKeyCannotBeModifiedException,
    PrimaryKeyCannotBeRepositionedException,
    SelfReferencingNonAssociationException,
)
from app.shared.domain.exceptions import DomainException

_UUID_REGEX = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_DANGEROUS_CHARS_REGEX = re.compile(r"[;<>'\"]|\bselect\b|\bdelete\b|\bupdate\b", re.IGNORECASE)


class DomainFailureCategory(str, Enum):
    """Categorías cerradas y seguras de fallos terminales de dominio."""

    CLASS_NOT_FOUND = "class_not_found"
    ATTRIBUTE_NOT_FOUND = "attribute_not_found"
    RELATION_NOT_FOUND = "relation_not_found"
    INCOMPATIBLE_DIAGRAM_STATE = "incompatible_diagram_state"
    GENERIC_DOMAIN_CONFLICT = "generic_domain_conflict"


@dataclass(frozen=True, slots=True)
class TerminalToolFailure:
    """Resultado inmutable de un conflicto de dominio terminal en herramientas."""

    category: DomainFailureCategory
    affected_element_type: str
    display_name: str | None
    task_id: str
    tool_name: str
    error_code: str
    has_confirmed_changes: bool = False

    def to_metadata(self) -> dict[str, Any]:
        """Proyección serializable para AiResult.metadata y el ledger."""
        return {
            "kind": "terminal_domain_failure",
            "category": self.category.value,
            "affected_element_type": self.affected_element_type,
            "display_name": self.display_name,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "error_code": self.error_code,
            "has_confirmed_changes": self.has_confirmed_changes,
        }


def sanitize_safe_display_name(raw_name: str | None) -> str | None:
    """Sanea nombres de elementos para visualización segura sin filtrar UUIDs ni código."""
    if not isinstance(raw_name, str):
        return None
    cleaned = raw_name.strip()
    if not cleaned:
        return None
    if _UUID_REGEX.search(cleaned):
        return None
    if _DANGEROUS_CHARS_REGEX.search(cleaned):
        return None
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rstrip()
    return cleaned


_EXCLUDED_DIAGRAM_EXCEPTIONS = (
    DiagramWriteForbiddenException,
    InvalidDiagramClassNameException,
    InvalidDiagramAttributeNameException,
    InvalidDiagramCoordinatesException,
    InvalidAttributePositionException,
    InvalidDiagramRelationNameException,
    InvalidDiagramRelationHandleException,
)

_SPECIFIC_INCOMPATIBLE_STATE_MAPPINGS: dict[type[Exception], tuple[str, str]] = {
    DiagramClassNameAlreadyExistsException: ("class_name_conflict", "class"),
    DiagramClassIdConflictException: ("class_id_conflict", "class"),
    DiagramAttributeIdConflictException: ("attribute_id_conflict", "attribute"),
    DiagramRelationIdConflictException: ("relation_id_conflict", "relation"),
    PrimaryKeyCannotBeDeletedException: ("primary_key_cannot_be_deleted", "attribute"),
    PrimaryKeyCannotBeModifiedException: ("primary_key_cannot_be_modified", "attribute"),
    PrimaryKeyCannotBeRepositionedException: ("primary_key_cannot_be_repositioned", "attribute"),
    ForeignKeyCannotBeDeletedException: ("foreign_key_cannot_be_deleted", "attribute"),
    ForeignKeyCannotBeModifiedException: ("foreign_key_cannot_be_modified", "attribute"),
    ForeignKeyCannotBeRepositionedException: ("foreign_key_cannot_be_repositioned", "attribute"),
    BridgeClassCannotBeDeletedDirectlyException: ("bridge_class_cannot_be_deleted_directly", "class"),
    DuplicateGeneralizationException: ("duplicate_generalization", "relation"),
    NonAssociativeRelationNameCannotBeModifiedException: ("relation_name_not_supported", "relation"),
    DiagramRelationSelfReferenceException: ("relation_self_reference", "relation"),
    SelfReferencingNonAssociationException: ("self_referencing_non_association", "relation"),
    InvalidDiagramRelationCardinalityException: ("invalid_relation_cardinality", "relation"),
    InvalidDiagramRelationMaterializationException: ("invalid_relation_materialization", "relation"),
    DiagramAgentLockedException: ("diagram_agent_locked", "diagram"),
}


def map_to_terminal_tool_failure(
    *,
    exc: Exception,
    task_id: str,
    tool_name: str,
    raw_target_name: str | None = None,
    has_confirmed_changes: bool = False,
) -> TerminalToolFailure | None:
    """Clasifica una excepción ocurrida durante la ejecución de herramientas.

    Devuelve un `TerminalToolFailure` tipado si corresponde a un conflicto de dominio
    terminal, o `None` si la excepción debe seguir las rutas existentes (corregible,
    proveedor, persistencia, cancelación, etc.).
    """
    if isinstance(exc, _EXCLUDED_DIAGRAM_EXCEPTIONS):
        return None

    # Exclusiones de excepciones del asistente que NO son fallos de dominio
    module_name = getattr(exc.__class__, "__module__", "")
    if "assistant" in module_name:
        return None

    safe_name = sanitize_safe_display_name(raw_target_name)

    # 1. Elementos ausentes
    if isinstance(exc, DiagramClassNotFoundException):
        return TerminalToolFailure(
            category=DomainFailureCategory.CLASS_NOT_FOUND,
            affected_element_type="class",
            display_name=safe_name,
            task_id=task_id,
            tool_name=tool_name,
            error_code="class_not_found",
            has_confirmed_changes=has_confirmed_changes,
        )

    if isinstance(exc, DiagramAttributeNotFoundException):
        return TerminalToolFailure(
            category=DomainFailureCategory.ATTRIBUTE_NOT_FOUND,
            affected_element_type="attribute",
            display_name=safe_name,
            task_id=task_id,
            tool_name=tool_name,
            error_code="attribute_not_found",
            has_confirmed_changes=has_confirmed_changes,
        )

    if isinstance(exc, DiagramRelationNotFoundException):
        return TerminalToolFailure(
            category=DomainFailureCategory.RELATION_NOT_FOUND,
            affected_element_type="relation",
            display_name=safe_name,
            task_id=task_id,
            tool_name=tool_name,
            error_code="relation_not_found",
            has_confirmed_changes=has_confirmed_changes,
        )

    # 2. Incompatibilidad de estado del diagrama
    for exc_cls, (error_code, element_type) in _SPECIFIC_INCOMPATIBLE_STATE_MAPPINGS.items():
        if isinstance(exc, exc_cls):
            return TerminalToolFailure(
                category=DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE,
                affected_element_type=element_type,
                display_name=safe_name,
                task_id=task_id,
                tool_name=tool_name,
                error_code=error_code,
                has_confirmed_changes=has_confirmed_changes,
            )

    # 3. Conflictos genéricos provenientes del dominio de diagrama
    if isinstance(exc, DomainException) and module_name.startswith("app.modules.diagram"):
        return TerminalToolFailure(
            category=DomainFailureCategory.GENERIC_DOMAIN_CONFLICT,
            affected_element_type="element",
            display_name=safe_name,
            task_id=task_id,
            tool_name=tool_name,
            error_code="domain_conflict",
            has_confirmed_changes=has_confirmed_changes,
        )

    return None


def format_terminal_failure_markdown(failure: TerminalToolFailure) -> str:
    """Genera la respuesta Markdown determinista, cordial y segura para el usuario."""
    name_clause = f" **{failure.display_name}**" if failure.display_name else ""

    if failure.category == DomainFailureCategory.CLASS_NOT_FOUND:
        base_msg = (
            f"No se pudo completar la solicitud porque la clase{name_clause} "
            "ya no está disponible en el diagrama."
        )
    elif failure.category == DomainFailureCategory.ATTRIBUTE_NOT_FOUND:
        base_msg = (
            f"No se pudo completar la solicitud porque el atributo{name_clause} "
            "ya no está disponible en la clase indicada."
        )
    elif failure.category == DomainFailureCategory.RELATION_NOT_FOUND:
        base_msg = (
            f"No se pudo completar la solicitud porque la relación{name_clause} "
            "ya no está disponible en el diagrama."
        )
    elif failure.category == DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE:
        base_msg = (
            "No se pudo completar la solicitud debido a un conflicto con el estado "
            "actual del diagrama."
        )
    else:
        base_msg = (
            "No se pudo completar la solicitud debido a un conflicto imprevisto con el "
            "estado del diagrama."
        )

    parts = [base_msg]

    if failure.has_confirmed_changes:
        parts.append(
            "Los cambios confirmados y aplicados anteriormente en esta solicitud "
            "se conservan intactos en el diagrama."
        )

    parts.append("Te sugerimos revisar el diagrama antes de volver a intentarlo.")

    if failure.category == DomainFailureCategory.CLASS_NOT_FOUND:
        if failure.display_name:
            parts.append(
                f"¿Deseas que cree la clase **{failure.display_name}** primero para poder continuar?"
            )
        else:
            parts.append("¿Deseas que cree la clase primero para poder continuar?")

    return "\n\n".join(parts)


def map_error_code_to_safe_reason(
    error_code: str | None, failure_reason: str | None = None
) -> str:
    """Proyecta un error_code o failure_reason a una descripción segura y limpia en español."""
    if failure_reason and isinstance(failure_reason, str) and failure_reason.strip():
        cleaned = failure_reason.strip()
        if not _UUID_REGEX.search(cleaned) and not _DANGEROUS_CHARS_REGEX.search(cleaned):
            return cleaned

    code = (error_code or "").lower()
    if "class_not_found" in code:
        return "la clase requerida ya no está disponible"
    if "attribute_not_found" in code:
        return "el atributo requerido ya no está disponible en la clase"
    if "relation_not_found" in code:
        return "la relación requerida ya no está disponible en el diagrama"
    if "blocked_by_" in code:
        return "bloqueada por fallo en una tarea previa"
    if "class_name_conflict" in code or "duplicate" in code:
        return "ya existe un elemento con el mismo nombre en el diagrama"
    if any(
        sub in code
        for sub in (
            "incompatible",
            "conflict",
            "cannot_be",
            "primary_key",
            "foreign_key",
            "bridge_class",
        )
    ):
        return "conflicto con el estado actual del diagrama"
    if code in {"timeout", "limit_exceeded"}:
        return "tiempo límite de ejecución excedido"
    return "no se pudo completar debido a un conflicto en el diagrama"

