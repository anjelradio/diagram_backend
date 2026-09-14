from uuid import UUID

from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.exceptions import (
    ForeignKeyCannotBeModifiedException,
    ForeignKeyCannotBeRepositionedException,
    InvalidAttributePositionException,
    InvalidDiagramAttributeNameException,
    InvalidDiagramRelationMaterializationException,
    PrimaryKeyCannotBeModifiedException,
    PrimaryKeyCannotBeRepositionedException,
)

UNSET = object()


class DiagramAttribute:
    """Entidad de dominio pura para un atributo de una clase de diagrama."""

    def __init__(
        self,
        id: UUID,
        class_id: UUID,
        name: str,
        data_type: DiagramAttributeDataType | None,
        position: int,
        is_primary_key: bool,
        is_nullable: bool,
        is_foreign_key: bool = False,
        referenced_class_id: UUID | None = None,
        relation_id: UUID | None = None,
    ) -> None:
        self.id = id
        self.class_id = class_id
        self._name = self._validate_name(name)
        self._is_primary_key = is_primary_key
        self._is_foreign_key = is_foreign_key

        if self._is_foreign_key:
            if referenced_class_id is None or relation_id is None:
                raise InvalidDiagramRelationMaterializationException()
            if data_type is not None and data_type != DiagramAttributeDataType.UUID:
                raise ForeignKeyCannotBeModifiedException()
            self._data_type = DiagramAttributeDataType.UUID
        else:
            if referenced_class_id is not None or relation_id is not None:
                raise InvalidDiagramRelationMaterializationException()
            self._data_type = data_type

        self.referenced_class_id = referenced_class_id
        self.relation_id = relation_id

        if self._is_primary_key:
            self._is_nullable = False
        else:
            self._is_nullable = is_nullable

        self._position = self._validate_position(position, is_primary_key)

    @property
    def name(self) -> str:
        return self._name

    @property
    def data_type(self) -> DiagramAttributeDataType | None:
        return self._data_type

    @property
    def position(self) -> int:
        return self._position

    @property
    def is_primary_key(self) -> bool:
        return self._is_primary_key

    @property
    def is_nullable(self) -> bool:
        return self._is_nullable

    @property
    def is_foreign_key(self) -> bool:
        return self._is_foreign_key

    @classmethod
    def _validate_name(cls, name: str) -> str:
        if not isinstance(name, str):
            raise InvalidDiagramAttributeNameException()
        cleaned = name.strip()
        if not cleaned or len(cleaned) > 255:
            raise InvalidDiagramAttributeNameException()
        return cleaned

    @classmethod
    def _validate_position(cls, position: int, is_primary_key: bool) -> int:
        if not isinstance(position, int):
            raise InvalidAttributePositionException()
        if is_primary_key:
            if position != 0:
                raise PrimaryKeyCannotBeRepositionedException()
        else:
            if position < 1:
                raise InvalidAttributePositionException()
        return position

    @classmethod
    def create_primary_key(
        cls, id: UUID, class_id: UUID, name: str = "id"
    ) -> "DiagramAttribute":
        """Crea el atributo de llave primaria fijado en posición 0, tipo UUID y no nullable."""
        return cls(
            id=id,
            class_id=class_id,
            name=name,
            data_type=DiagramAttributeDataType.UUID,
            position=0,
            is_primary_key=True,
            is_nullable=False,
            is_foreign_key=False,
            referenced_class_id=None,
            relation_id=None,
        )

    @classmethod
    def create_secondary(
        cls, id: UUID, class_id: UUID, name: str, position: int
    ) -> "DiagramAttribute":
        """Crea un atributo secundario con tipo null por defecto y nullable."""
        return cls(
            id=id,
            class_id=class_id,
            name=name,
            data_type=None,
            position=position,
            is_primary_key=False,
            is_nullable=True,
            is_foreign_key=False,
            referenced_class_id=None,
            relation_id=None,
        )

    @classmethod
    def create_foreign_key(
        cls,
        id: UUID,
        class_id: UUID,
        name: str,
        position: int,
        referenced_class_id: UUID,
        relation_id: UUID,
        is_nullable: bool = False,
    ) -> "DiagramAttribute":
        """Crea un atributo secundario FK derivado de una relación."""
        return cls(
            id=id,
            class_id=class_id,
            name=name,
            data_type=DiagramAttributeDataType.UUID,
            position=position,
            is_primary_key=False,
            is_nullable=is_nullable,
            is_foreign_key=True,
            referenced_class_id=referenced_class_id,
            relation_id=relation_id,
        )

    @classmethod
    def create_shared_primary_key(
        cls,
        id: UUID,
        class_id: UUID,
        referenced_class_id: UUID,
        relation_id: UUID,
        name: str = "id",
    ) -> "DiagramAttribute":
        """Crea una llave primaria compartida para una subclase en generalización."""
        return cls(
            id=id,
            class_id=class_id,
            name=name,
            data_type=DiagramAttributeDataType.UUID,
            position=0,
            is_primary_key=True,
            is_nullable=False,
            is_foreign_key=True,
            referenced_class_id=referenced_class_id,
            relation_id=relation_id,
        )

    def update_details(
        self,
        name: str | object = UNSET,
        data_type: DiagramAttributeDataType | None | object = UNSET,
        is_nullable: bool | object = UNSET,
    ) -> None:
        """Actualiza parcialmente los detalles del atributo protegiendo la llave primaria y FKs."""
        if self._is_primary_key:
            raise PrimaryKeyCannotBeModifiedException()

        if self._is_foreign_key:
            if data_type is not UNSET and data_type != DiagramAttributeDataType.UUID:
                raise ForeignKeyCannotBeModifiedException()
            if is_nullable is not UNSET and bool(is_nullable) != self._is_nullable:
                raise ForeignKeyCannotBeModifiedException()

        if name is not UNSET:
            self._name = self._validate_name(name)  # type: ignore[arg-type]
        if data_type is not UNSET and not self._is_foreign_key:
            self._data_type = data_type  # type: ignore[assignment]
        if is_nullable is not UNSET and not self._is_foreign_key:
            self._is_nullable = bool(is_nullable)

    def reposition(self, new_position: int) -> None:
        """Actualiza la posición ordinal de un atributo secundario protegiendo PK y FK."""
        if self._is_primary_key:
            raise PrimaryKeyCannotBeRepositionedException()
        if self._is_foreign_key:
            raise ForeignKeyCannotBeRepositionedException()
        if not isinstance(new_position, int) or new_position < 1:
            raise InvalidAttributePositionException()
        self._position = new_position

    def compact_position(self, new_position: int) -> None:
        """Actualiza la posición ordinal de un atributo secundario durante compactación interna."""
        if self._is_primary_key:
            raise PrimaryKeyCannotBeRepositionedException()
        if not isinstance(new_position, int) or new_position < 1:
            raise InvalidAttributePositionException()
        self._position = new_position

    def as_shared_primary_key(
        self, referenced_class_id: UUID, relation_id: UUID
    ) -> None:
        """Promueve la PK existente a PK/FK compartida referenciando a la superclase."""
        if not self._is_primary_key:
            raise PrimaryKeyCannotBeRepositionedException()
        self._is_foreign_key = True
        self.referenced_class_id = referenced_class_id
        self.relation_id = relation_id

    def revert_shared_primary_key(self) -> None:
        """Revierte una PK compartida a PK normal sin referencia foránea."""
        if self._is_primary_key and self._is_foreign_key:
            self._is_foreign_key = False
            self.referenced_class_id = None
            self.relation_id = None
