import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_relation_table_and_cascade(
    session: Session,
    test_project: ProjectModel,
    two_classes: tuple[DiagramClassModel, DiagramClassModel],
):
    source_class, target_class = two_classes
    relation_id = uuid.uuid4()

    rel_model = DiagramRelationModel(
        id=relation_id,
        project_id=test_project.id,
        source_class_id=source_class.id,
        target_class_id=target_class.id,
        relation_type="ASSOCIATION",
        source_handle="RIGHT_CENTER",
        target_handle="LEFT_CENTER",
        name="Trabaja con",
        source_cardinality="1",
        target_cardinality="0..*",
    )
    session.add(rel_model)
    session.flush()

    fk_attr = DiagramAttributeModel(
        id=uuid.uuid4(),
        class_id=target_class.id,
        name="source_id",
        data_type="UUID",
        position=1,
        is_primary_key=False,
        is_nullable=False,
        is_foreign_key=True,
        referenced_class_id=source_class.id,
        relation_id=relation_id,
    )
    session.add(fk_attr)
    session.commit()

    fk_attr_id = fk_attr.id
    # Verificar que existen en BD
    assert session.get(DiagramRelationModel, relation_id) is not None
    assert session.get(DiagramAttributeModel, fk_attr_id) is not None

    # Eliminar la relación -> debe eliminar la FK en cascada
    session.delete(rel_model)
    session.commit()
    session.expunge_all()

    assert session.get(DiagramRelationModel, relation_id) is None
    # Atributo FK derivado eliminado
    assert session.get(DiagramAttributeModel, fk_attr_id) is None


def test_check_constraint_rejects_self_reference(
    session: Session,
    test_project: ProjectModel,
    two_classes: tuple[DiagramClassModel, DiagramClassModel],
):
    source_class, _ = two_classes

    # Intentar autorrelación directamente en base de datos
    invalid_rel = DiagramRelationModel(
        id=uuid.uuid4(),
        project_id=test_project.id,
        source_class_id=source_class.id,
        target_class_id=source_class.id,
        relation_type="ASSOCIATION",
        source_handle="TOP_CENTER",
        target_handle="BOTTOM_CENTER",
        name="Self",
        source_cardinality="1",
        target_cardinality="1",
    )
    session.add(invalid_rel)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_check_constraint_rejects_inconsistent_fk_attribute(
    session: Session,
    two_classes: tuple[DiagramClassModel, DiagramClassModel],
):
    source_class, _ = two_classes

    # Atributo marcado como is_foreign_key=True pero sin referenced_class_id ni relation_id
    invalid_attr = DiagramAttributeModel(
        id=uuid.uuid4(),
        class_id=source_class.id,
        name="bad_fk",
        data_type="UUID",
        position=1,
        is_primary_key=False,
        is_nullable=True,
        is_foreign_key=True,
        referenced_class_id=None,
        relation_id=None,
    )
    session.add(invalid_attr)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
