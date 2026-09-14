import uuid
import pytest

from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.domain.exceptions import (
    DiagramRelationSelfReferenceException,
    InvalidDiagramRelationCardinalityException,
    InvalidDiagramRelationHandleException,
    InvalidDiagramRelationMaterializationException,
    InvalidDiagramRelationNameException,
    ManyToManyRelationNameCannotBeModifiedException,
)


def test_create_valid_association():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    rel_id = uuid.uuid4()

    rel = DiagramRelation.create(
        id=rel_id,
        project_id=project_id,
        source_class_id=source_id,
        target_class_id=target_id,
        relation_type=DiagramRelationType.ASSOCIATION,
        source_handle=DiagramRelationHandle.RIGHT_CENTER,
        target_handle=DiagramRelationHandle.LEFT_CENTER,
        name="Trabaja en",
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )

    assert rel.id == rel_id
    assert rel.name == "Trabaja en"
    assert rel.relation_type == DiagramRelationType.ASSOCIATION
    assert rel.source_cardinality == DiagramCardinality.EXACTLY_ONE
    assert rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE
    assert rel.source_handle == DiagramRelationHandle.RIGHT_CENTER
    assert rel.target_handle == DiagramRelationHandle.LEFT_CENTER
    assert rel.bridge_class_id is None
    assert not rel.is_many_to_many


def test_reject_self_reference():
    project_id = uuid.uuid4()
    class_id = uuid.uuid4()

    with pytest.raises(DiagramRelationSelfReferenceException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=class_id,
            target_class_id=class_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle=DiagramRelationHandle.TOP_CENTER,
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=DiagramCardinality.EXACTLY_ONE,
        )


def test_association_requires_both_cardinalities():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Falta target_cardinality
    with pytest.raises(InvalidDiagramRelationCardinalityException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle=DiagramRelationHandle.TOP_CENTER,
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=None,
        )

    # Falta source_cardinality
    with pytest.raises(InvalidDiagramRelationCardinalityException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle=DiagramRelationHandle.TOP_CENTER,
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            source_cardinality=None,
            target_cardinality=DiagramCardinality.ZERO_OR_MORE,
        )


@pytest.mark.parametrize(
    "rel_type",
    [
        DiagramRelationType.AGGREGATION,
        DiagramRelationType.COMPOSITION,
        DiagramRelationType.GENERALIZATION,
        DiagramRelationType.REALIZATION,
        DiagramRelationType.DEPENDENCY,
    ],
)
def test_non_associative_relations_forbid_cardinalities_and_names(rel_type):
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Válido sin cardinalidades y con nombre vacío
    rel = DiagramRelation.create(
        id=uuid.uuid4(),
        project_id=project_id,
        source_class_id=source_id,
        target_class_id=target_id,
        relation_type=rel_type,
        source_handle=DiagramRelationHandle.TOP_CENTER,
        target_handle=DiagramRelationHandle.BOTTOM_CENTER,
        name="",
        source_cardinality=None,
        target_cardinality=None,
    )
    assert rel.source_cardinality is None
    assert rel.target_cardinality is None
    assert rel.name == ""

    # Inválido si se envía nombre no vacío
    with pytest.raises(InvalidDiagramRelationNameException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=rel_type,
            source_handle=DiagramRelationHandle.TOP_CENTER,
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            name="NombreProhibido",
            source_cardinality=None,
            target_cardinality=None,
        )

    # Renombrar tipo no asociativo debe fallar con 409 (NonAssociativeRelationNameCannotBeModifiedException)
    from app.modules.diagram.domain.exceptions import (
        NonAssociativeRelationNameCannotBeModifiedException,
    )

    with pytest.raises(NonAssociativeRelationNameCannotBeModifiedException):
        rel.rename("Intento")

    # Inválido si se envían cardinalidades
    with pytest.raises(InvalidDiagramRelationCardinalityException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=rel_type,
            source_handle=DiagramRelationHandle.TOP_CENTER,
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=DiagramCardinality.EXACTLY_ONE,
        )


def test_invalid_handles():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    with pytest.raises(InvalidDiagramRelationHandleException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle="INVALID_HANDLE",  # type: ignore
            target_handle=DiagramRelationHandle.BOTTOM_CENTER,
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=DiagramCardinality.EXACTLY_ONE,
        )


def test_many_to_many_requires_bridge_class_and_supports_name():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    bridge_id = uuid.uuid4()

    # Falla sin bridge_class_id
    with pytest.raises(InvalidDiagramRelationMaterializationException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle=DiagramRelationHandle.RIGHT_CENTER,
            target_handle=DiagramRelationHandle.LEFT_CENTER,
            source_cardinality=DiagramCardinality.ZERO_OR_MORE,
            target_cardinality=DiagramCardinality.ZERO_OR_MORE,
            bridge_class_id=None,
        )

    # Éxito con bridge_class_id: ASSOCIATION N:M tiene nombre por defecto y es editable
    nm_rel = DiagramRelation.create(
        id=uuid.uuid4(),
        project_id=project_id,
        source_class_id=source_id,
        target_class_id=target_id,
        relation_type=DiagramRelationType.ASSOCIATION,
        source_handle=DiagramRelationHandle.RIGHT_CENTER,
        target_handle=DiagramRelationHandle.LEFT_CENTER,
        name="Nueva relación",
        source_cardinality=DiagramCardinality.ZERO_OR_MORE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
        bridge_class_id=bridge_id,
        bridge_handle=DiagramRelationHandle.TOP_CENTER,
    )
    assert nm_rel.is_many_to_many
    assert nm_rel.name == "Nueva relación"
    assert nm_rel.bridge_class_id == bridge_id

    # Renombrar N:M debe ser exitoso al ser una asociación
    nm_rel.rename("Autores Libros")
    assert nm_rel.name == "Autores Libros"

    # Nombre vacío en asociación debe fallar
    with pytest.raises(InvalidDiagramRelationNameException):
        nm_rel.rename("   ")


def test_non_many_to_many_forbids_bridge_class():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    bridge_id = uuid.uuid4()

    with pytest.raises(InvalidDiagramRelationMaterializationException):
        DiagramRelation.create(
            id=uuid.uuid4(),
            project_id=project_id,
            source_class_id=source_id,
            target_class_id=target_id,
            relation_type=DiagramRelationType.ASSOCIATION,
            source_handle=DiagramRelationHandle.RIGHT_CENTER,
            target_handle=DiagramRelationHandle.LEFT_CENTER,
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=DiagramCardinality.ZERO_OR_MORE,
            bridge_class_id=bridge_id,
        )


def test_rename_relation():
    project_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    rel = DiagramRelation.create(
        id=uuid.uuid4(),
        project_id=project_id,
        source_class_id=source_id,
        target_class_id=target_id,
        relation_type=DiagramRelationType.ASSOCIATION,
        source_handle=DiagramRelationHandle.RIGHT_CENTER,
        target_handle=DiagramRelationHandle.LEFT_CENTER,
        name="Inicial",
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.EXACTLY_ONE,
    )

    rel.rename("  Actualizado  ")
    assert rel.name == "Actualizado"

    with pytest.raises(InvalidDiagramRelationNameException):
        rel.rename("a" * 256)
