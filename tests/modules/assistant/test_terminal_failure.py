"""Pruebas unitarias de clasificación y formato de fallos terminales de dominio.

Cumple con T005, FR-001, FR-006, FR-007, FR-008, SC-002 y SC-005:
- Clasificación determinista de excepciones de dominio en categorías seguras.
- Exclusión estricta de excepciones de proveedor, persistencia, argumentos y timeout.
- Saneamiento de nombres y censura de UUIDs/detalles técnicos.
- Generación de Markdown predefinido cordial, claro y accionable.
"""

import re
from uuid import uuid4

import pytest

from app.modules.assistant.application.services.execution.terminal_failure import (
    DomainFailureCategory,
    TerminalToolFailure,
    format_terminal_failure_markdown,
    map_to_terminal_tool_failure,
    sanitize_safe_display_name,
)
from app.modules.assistant.domain.exceptions import (
    AgentAmbiguousClassException,
    AgentMessagePersistenceException,
    AgentToolArgumentsException,
    AgentToolLimitException,
    AiProviderError,
    AiProviderUnavailableException,
    InvalidExecutionPlanException,
)
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


def test_sanitize_safe_display_name():
    # Nombre normal
    assert sanitize_safe_display_name("Cliente") == "Cliente"
    assert sanitize_safe_display_name("  Usuario  ") == "Usuario"

    # UUID completo debe ser purgado
    raw_uuid = str(uuid4())
    assert sanitize_safe_display_name(raw_uuid) is None
    assert sanitize_safe_display_name(f"clase_{raw_uuid}") is None

    # Nombres que superan el límite de longitud
    long_name = "A" * 150
    sanitized = sanitize_safe_display_name(long_name)
    assert sanitized is not None
    assert len(sanitized) <= 60

    # Nombres vacíos o con caracteres inválidos
    assert sanitize_safe_display_name("") is None
    assert sanitize_safe_display_name("   ") is None
    assert sanitize_safe_display_name("SELECT * FROM users") is None


def test_terminal_tool_failure_immutability():
    failure = TerminalToolFailure(
        category=DomainFailureCategory.CLASS_NOT_FOUND,
        affected_element_type="class",
        display_name="Factura",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        error_code="class_not_found",
        has_confirmed_changes=False,
    )
    with pytest.raises(Exception):
        failure.category = DomainFailureCategory.GENERIC_DOMAIN_CONFLICT  # type: ignore[misc]


def test_map_class_not_found():
    exc = DiagramClassNotFoundException()
    failure = map_to_terminal_tool_failure(
        exc=exc,
        task_id="task-del",
        tool_name="apply_diagram_changes",
        raw_target_name="Cliente",
        has_confirmed_changes=True,
    )
    assert failure is not None
    assert failure.category == DomainFailureCategory.CLASS_NOT_FOUND
    assert failure.affected_element_type == "class"
    assert failure.display_name == "Cliente"
    assert failure.task_id == "task-del"
    assert failure.tool_name == "apply_diagram_changes"
    assert failure.error_code == "class_not_found"
    assert failure.has_confirmed_changes is True


def test_map_attribute_not_found():
    exc = DiagramAttributeNotFoundException()
    failure = map_to_terminal_tool_failure(
        exc=exc,
        task_id="task-attr",
        tool_name="apply_diagram_changes",
        raw_target_name="email",
        has_confirmed_changes=False,
    )
    assert failure is not None
    assert failure.category == DomainFailureCategory.ATTRIBUTE_NOT_FOUND
    assert failure.affected_element_type == "attribute"
    assert failure.display_name == "email"
    assert failure.error_code == "attribute_not_found"


def test_map_relation_not_found():
    exc = DiagramRelationNotFoundException()
    failure = map_to_terminal_tool_failure(
        exc=exc,
        task_id="task-rel",
        tool_name="apply_diagram_changes",
        raw_target_name="posee",
        has_confirmed_changes=False,
    )
    assert failure is not None
    assert failure.category == DomainFailureCategory.RELATION_NOT_FOUND
    assert failure.affected_element_type == "relation"
    assert failure.display_name == "posee"
    assert failure.error_code == "relation_not_found"


@pytest.mark.parametrize(
    "exc,expected_code,expected_element",
    [
        (DiagramClassNameAlreadyExistsException(), "class_name_conflict", "class"),
        (DiagramClassIdConflictException(), "class_id_conflict", "class"),
        (DiagramAttributeIdConflictException(), "attribute_id_conflict", "attribute"),
        (DiagramRelationIdConflictException(), "relation_id_conflict", "relation"),
        (PrimaryKeyCannotBeDeletedException(), "primary_key_cannot_be_deleted", "attribute"),
        (PrimaryKeyCannotBeModifiedException(), "primary_key_cannot_be_modified", "attribute"),
        (PrimaryKeyCannotBeRepositionedException(), "primary_key_cannot_be_repositioned", "attribute"),
        (ForeignKeyCannotBeDeletedException(), "foreign_key_cannot_be_deleted", "attribute"),
        (ForeignKeyCannotBeModifiedException(), "foreign_key_cannot_be_modified", "attribute"),
        (ForeignKeyCannotBeRepositionedException(), "foreign_key_cannot_be_repositioned", "attribute"),
        (BridgeClassCannotBeDeletedDirectlyException(), "bridge_class_cannot_be_deleted_directly", "class"),
        (DuplicateGeneralizationException(), "duplicate_generalization", "relation"),
        (NonAssociativeRelationNameCannotBeModifiedException(), "relation_name_not_supported", "relation"),
        (DiagramRelationSelfReferenceException(), "relation_self_reference", "relation"),
        (SelfReferencingNonAssociationException(), "self_referencing_non_association", "relation"),
        (InvalidDiagramRelationCardinalityException(), "invalid_relation_cardinality", "relation"),
        (InvalidDiagramRelationMaterializationException(), "invalid_relation_materialization", "relation"),
        (DiagramAgentLockedException(), "diagram_agent_locked", "diagram"),
    ],
)
def test_map_incompatible_diagram_state(exc, expected_code, expected_element):
    failure = map_to_terminal_tool_failure(
        exc=exc,
        task_id="task-check",
        tool_name="apply_diagram_changes",
        raw_target_name="Elemento",
        has_confirmed_changes=False,
    )
    assert failure is not None
    assert failure.category == DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE
    assert failure.error_code == expected_code
    assert failure.affected_element_type == expected_element


def test_map_generic_diagram_domain_exception():
    class CustomDiagramConflict(DomainException):
        __module__ = "app.modules.diagram.domain.exceptions"
        code = "CUSTOM_DIAGRAM_CONFLICT"
        message = "Conflicto custom"

    failure = map_to_terminal_tool_failure(
        exc=CustomDiagramConflict(),
        task_id="task-generic",
        tool_name="apply_diagram_changes",
        raw_target_name=None,
        has_confirmed_changes=True,
    )
    assert failure is not None
    assert failure.category == DomainFailureCategory.GENERIC_DOMAIN_CONFLICT
    assert failure.error_code == "domain_conflict"
    assert failure.has_confirmed_changes is True


@pytest.mark.parametrize(
    "exc",
    [
        AgentToolArgumentsException(),
        AgentAmbiguousClassException(name="ClaseA", candidate_ids=["id1", "id2"]),
        InvalidDiagramClassNameException(),
        InvalidDiagramAttributeNameException(),
        InvalidDiagramCoordinatesException(),
        InvalidAttributePositionException(),
        InvalidDiagramRelationNameException(),
        InvalidDiagramRelationHandleException(),
        DiagramWriteForbiddenException(),
        AiProviderError(),
        AiProviderUnavailableException(),
        AgentMessagePersistenceException(),
        AgentToolLimitException(),
        InvalidExecutionPlanException(),
        TimeoutError("timeout"),
        RuntimeError("crash"),
        KeyError("missing_key"),
    ],
)
def test_unmapped_exceptions_are_not_terminal_domain_failures(exc):
    failure = map_to_terminal_tool_failure(
        exc=exc,
        task_id="task-unmapped",
        tool_name="apply_diagram_changes",
        raw_target_name=None,
        has_confirmed_changes=False,
    )
    assert failure is None


def test_format_terminal_failure_markdown_without_prior_commits():
    failure = TerminalToolFailure(
        category=DomainFailureCategory.CLASS_NOT_FOUND,
        affected_element_type="class",
        display_name="Pedido",
        task_id="task-1",
        tool_name="apply_diagram_changes",
        error_code="class_not_found",
        has_confirmed_changes=False,
    )
    md = format_terminal_failure_markdown(failure)
    assert "No se pudo completar la solicitud" in md
    assert "Pedido" in md
    assert "ya no está disponible en el diagrama" in md
    assert "¿deseas que cree la clase" in md.lower()
    # No debe decir que se conservan cambios previos porque has_confirmed_changes=False
    assert "cambios confirmados" not in md.lower()
    # Invariante SC-002: cero UUIDs técnicos
    assert "-" not in md or not any(len(part) == 36 for part in md.split())


def test_format_terminal_failure_markdown_with_prior_commits():
    failure = TerminalToolFailure(
        category=DomainFailureCategory.ATTRIBUTE_NOT_FOUND,
        affected_element_type="attribute",
        display_name="precio",
        task_id="task-2",
        tool_name="apply_diagram_changes",
        error_code="attribute_not_found",
        has_confirmed_changes=True,
    )
    md = format_terminal_failure_markdown(failure)
    assert "No se pudo completar la solicitud" in md
    assert "precio" in md
    # Debe advertir explícitamente que los cambios previos confirmados se conservan (FR-005, SC-004)
    assert "cambios confirmados" in md.lower() or "cambios ya aplicados" in md.lower()


def test_format_terminal_failure_markdown_generic_conflict():
    failure = TerminalToolFailure(
        category=DomainFailureCategory.GENERIC_DOMAIN_CONFLICT,
        affected_element_type="element",
        display_name=None,
        task_id="task-3",
        tool_name="apply_diagram_changes",
        error_code="domain_conflict",
        has_confirmed_changes=False,
    )
    md = format_terminal_failure_markdown(failure)
    assert "No se pudo completar la solicitud" in md
    assert "conflicto" in md.lower()
    assert "diagrama" in md.lower()


@pytest.mark.parametrize(
    "category,display_name,expected_phrase",
    [
        (DomainFailureCategory.CLASS_NOT_FOUND, "Factura", "la clase **Factura** ya no está disponible en el diagrama."),
        (DomainFailureCategory.CLASS_NOT_FOUND, None, "la clase ya no está disponible en el diagrama."),
        (DomainFailureCategory.ATTRIBUTE_NOT_FOUND, "saldo", "el atributo **saldo** ya no está disponible en la clase indicada."),
        (DomainFailureCategory.ATTRIBUTE_NOT_FOUND, None, "el atributo ya no está disponible en la clase indicada."),
        (DomainFailureCategory.RELATION_NOT_FOUND, "pertenece", "la relación **pertenece** ya no está disponible en el diagrama."),
        (DomainFailureCategory.RELATION_NOT_FOUND, None, "la relación ya no está disponible en el diagrama."),
        (DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE, "Cualquiera", "conflicto con el estado actual del diagrama."),
        (DomainFailureCategory.INCOMPATIBLE_DIAGRAM_STATE, None, "conflicto con el estado actual del diagrama."),
        (DomainFailureCategory.GENERIC_DOMAIN_CONFLICT, "Cualquiera", "conflicto imprevisto con el estado del diagrama."),
        (DomainFailureCategory.GENERIC_DOMAIN_CONFLICT, None, "conflicto imprevisto con el estado del diagrama."),
    ],
)
def test_format_terminal_failure_markdown_all_categories(category, display_name, expected_phrase):
    failure = TerminalToolFailure(
        category=category,
        affected_element_type="element",
        display_name=display_name,
        task_id="task-test",
        tool_name="apply_diagram_changes",
        error_code="test_code",
        has_confirmed_changes=False,
    )
    md = format_terminal_failure_markdown(failure)
    assert expected_phrase in md
    if category == DomainFailureCategory.CLASS_NOT_FOUND:
        assert md.endswith("para poder continuar?")
    else:
        assert md.endswith("Te sugerimos revisar el diagrama antes de volver a intentarlo.")


@pytest.mark.parametrize("category", list(DomainFailureCategory))
@pytest.mark.parametrize("has_confirmed", [True, False])
def test_format_terminal_failure_markdown_strictly_excludes_forbidden_content(category, has_confirmed):
    failure = TerminalToolFailure(
        category=category,
        affected_element_type="class",
        display_name="Cliente",
        task_id="task-test-forbidden",
        tool_name="apply_diagram_changes",
        error_code="class_not_found",
        has_confirmed_changes=has_confirmed,
    )
    md = format_terminal_failure_markdown(failure)

    # 1. Sin UUIDs
    uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
    assert not uuid_pattern.search(md)

    # 2. Sin palabras clave de SQL ni código
    for keyword in ["select", "insert", "update", "delete", "from", "where", "drop table"]:
        assert not re.search(rf"\b{keyword}\b", md, re.IGNORECASE)

    # 3. Sin nombres de excepciones ni clases técnicas
    forbidden_terms = [
        "Exception",
        "Traceback",
        "Error",
        "DiagramClassNotFoundException",
        "SQLAlchemy",
        "task-test-forbidden",
        "apply_diagram_changes",
    ]
    for term in forbidden_terms:
        assert term not in md

    # 4. Orientación accionable obligatoria
    if category == DomainFailureCategory.CLASS_NOT_FOUND:
        assert "¿deseas que cree la clase" in md.lower()
    else:
        assert "revisar el diagrama antes de volver a intentarlo" in md

    # 5. Mención de cambios confirmados condicionada estrictamente a has_confirmed_changes
    confirmed_phrase = "Los cambios confirmados y aplicados anteriormente en esta solicitud se conservan intactos en el diagrama."
    if has_confirmed:
        assert confirmed_phrase in md
    else:
        assert confirmed_phrase not in md

