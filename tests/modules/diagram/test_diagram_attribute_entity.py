import uuid
import pytest

from app.modules.diagram.domain.entities.diagram_attribute import DiagramAttribute
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.exceptions import (
    InvalidAttributePositionException,
    InvalidDiagramAttributeNameException,
    PrimaryKeyCannotBeModifiedException,
    PrimaryKeyCannotBeRepositionedException,
)


def test_create_primary_key_factory():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    pk = DiagramAttribute.create_primary_key(id=attr_id, class_id=class_id)

    assert pk.id == attr_id
    assert pk.class_id == class_id
    assert pk.name == "id"
    assert pk.data_type == DiagramAttributeDataType.UUID
    assert pk.position == 0
    assert pk.is_primary_key is True
    assert pk.is_nullable is False


def test_create_primary_key_with_custom_name():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    pk = DiagramAttribute.create_primary_key(
        id=attr_id, class_id=class_id, name="codigo_uuid"
    )

    assert pk.name == "codigo_uuid"
    assert pk.data_type == DiagramAttributeDataType.UUID
    assert pk.position == 0


def test_primary_key_invariants_reject_invalid_position():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    with pytest.raises(PrimaryKeyCannotBeRepositionedException):
        DiagramAttribute(
            id=attr_id,
            class_id=class_id,
            name="id",
            data_type=DiagramAttributeDataType.UUID,
            position=1,  # Invalido para PK
            is_primary_key=True,
            is_nullable=False,
        )


def test_create_secondary_factory():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    sec = DiagramAttribute.create_secondary(
        id=attr_id, class_id=class_id, name="precio", position=1
    )

    assert sec.id == attr_id
    assert sec.class_id == class_id
    assert sec.name == "precio"
    assert sec.data_type is None
    assert sec.position == 1
    assert sec.is_primary_key is False
    assert sec.is_nullable is True


def test_secondary_attribute_invariants_reject_invalid_position():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    with pytest.raises(InvalidAttributePositionException):
        DiagramAttribute.create_secondary(
            id=attr_id, class_id=class_id, name="precio", position=0
        )

    with pytest.raises(InvalidAttributePositionException):
        DiagramAttribute.create_secondary(
            id=attr_id, class_id=class_id, name="precio", position=-1
        )


@pytest.mark.parametrize("invalid_name", ["", "   ", "a" * 256])
def test_diagram_attribute_name_validation(invalid_name):
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    with pytest.raises(InvalidDiagramAttributeNameException):
        DiagramAttribute.create_secondary(
            id=attr_id, class_id=class_id, name=invalid_name, position=1
        )


def test_diagram_attribute_name_stripping():
    attr_id = uuid.uuid4()
    class_id = uuid.uuid4()

    sec = DiagramAttribute.create_secondary(
        id=attr_id, class_id=class_id, name="  descripcion  ", position=1
    )
    assert sec.name == "descripcion"


def test_primary_key_cannot_be_renamed():
    pk = DiagramAttribute.create_primary_key(id=uuid.uuid4(), class_id=uuid.uuid4())

    with pytest.raises(PrimaryKeyCannotBeModifiedException):
        pk.update_details(name="identificador")


def test_primary_key_type_modification_rejected():
    pk = DiagramAttribute.create_primary_key(id=uuid.uuid4(), class_id=uuid.uuid4())

    with pytest.raises(PrimaryKeyCannotBeModifiedException):
        pk.update_details(data_type=DiagramAttributeDataType.TEXT)

    with pytest.raises(PrimaryKeyCannotBeModifiedException):
        pk.update_details(data_type=None)


def test_primary_key_nullability_modification_rejected():
    pk = DiagramAttribute.create_primary_key(id=uuid.uuid4(), class_id=uuid.uuid4())

    with pytest.raises(PrimaryKeyCannotBeModifiedException):
        pk.update_details(is_nullable=True)


def test_primary_key_cannot_be_repositioned():
    pk = DiagramAttribute.create_primary_key(id=uuid.uuid4(), class_id=uuid.uuid4())

    with pytest.raises(PrimaryKeyCannotBeRepositionedException):
        pk.reposition(2)


def test_secondary_attribute_update_details():
    sec = DiagramAttribute.create_secondary(
        id=uuid.uuid4(), class_id=uuid.uuid4(), name="campo", position=1
    )

    sec.update_details(
        name="precio_unitario",
        data_type=DiagramAttributeDataType.DECIMAL,
        is_nullable=False,
    )

    assert sec.name == "precio_unitario"
    assert sec.data_type == DiagramAttributeDataType.DECIMAL
    assert sec.is_nullable is False

    # Volver a data_type None (sin asignar)
    sec.update_details(data_type=None)
    assert sec.data_type is None


def test_secondary_attribute_reposition():
    sec = DiagramAttribute.create_secondary(
        id=uuid.uuid4(), class_id=uuid.uuid4(), name="campo", position=1
    )

    sec.reposition(4)
    assert sec.position == 4

    with pytest.raises(InvalidAttributePositionException):
        sec.reposition(0)
