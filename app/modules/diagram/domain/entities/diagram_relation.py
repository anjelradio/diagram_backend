from uuid import UUID

from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
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
    NonAssociativeRelationNameCannotBeModifiedException,
    SelfReferencingNonAssociationException,
)


class DiagramRelation:
    """Entidad de dominio pura que representa una relación UML en el diagrama."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        source_class_id: UUID,
        target_class_id: UUID,
        relation_type: DiagramRelationType,
        source_handle: DiagramRelationHandle,
        target_handle: DiagramRelationHandle,
        name: str = "Nueva relación",
        source_cardinality: DiagramCardinality | None = None,
        target_cardinality: DiagramCardinality | None = None,
        bridge_class_id: UUID | None = None,
        bridge_handle: DiagramRelationHandle | None = None,
    ) -> None:
        if source_class_id == target_class_id:
            if relation_type != DiagramRelationType.ASSOCIATION:
                raise SelfReferencingNonAssociationException()
            if source_handle == target_handle:
                raise InvalidDiagramRelationHandleException(
                    "Una relación recursiva debe utilizar handles distintos en origen y destino."
                )

        self.id = id
        self.project_id = project_id
        self.source_class_id = source_class_id
        self.target_class_id = target_class_id
        self.relation_type = relation_type

        self.source_handle = self._validate_handle(source_handle)
        self.target_handle = self._validate_handle(target_handle)

        self._validate_cardinalities(
            relation_type, source_cardinality, target_cardinality
        )
        self.source_cardinality = source_cardinality
        self.target_cardinality = target_cardinality

        is_nm = self._compute_is_many_to_many(
            relation_type, source_cardinality, target_cardinality
        )

        if is_nm:
            if bridge_class_id is None:
                raise InvalidDiagramRelationMaterializationException()
            self.bridge_class_id = bridge_class_id
            self.bridge_handle = self._validate_handle(
                bridge_handle or DiagramRelationHandle.TOP_CENTER
            )
        else:
            if bridge_class_id is not None or bridge_handle is not None:
                raise InvalidDiagramRelationMaterializationException()
            self.bridge_class_id = None
            self.bridge_handle = None

        if relation_type == DiagramRelationType.ASSOCIATION:
            self._name = self._validate_name(name)
        else:
            if name and isinstance(name, str) and name.strip() != "":
                raise InvalidDiagramRelationNameException(
                    "Las relaciones no asociativas deben conservar el nombre vacío."
                )
            self._name = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_many_to_many(self) -> bool:
        return self._compute_is_many_to_many(
            self.relation_type, self.source_cardinality, self.target_cardinality
        )

    @staticmethod
    def _compute_is_many_to_many(
        relation_type: DiagramRelationType,
        source_card: DiagramCardinality | None,
        target_card: DiagramCardinality | None,
    ) -> bool:
        if relation_type != DiagramRelationType.ASSOCIATION:
            return False
        if source_card is None or target_card is None:
            return False
        source_many = source_card in (
            DiagramCardinality.ZERO_OR_MORE,
            DiagramCardinality.ONE_OR_MORE,
        )
        target_many = target_card in (
            DiagramCardinality.ZERO_OR_MORE,
            DiagramCardinality.ONE_OR_MORE,
        )
        return source_many and target_many

    @classmethod
    def _validate_handle(cls, handle: DiagramRelationHandle | str) -> DiagramRelationHandle:
        try:
            return DiagramRelationHandle(handle)
        except (ValueError, TypeError):
            raise InvalidDiagramRelationHandleException()

    @classmethod
    def _validate_name(cls, name: str) -> str:
        if not isinstance(name, str):
            raise InvalidDiagramRelationNameException()
        cleaned = name.strip()
        if not cleaned or len(cleaned) > 255:
            raise InvalidDiagramRelationNameException()
        return cleaned

    @classmethod
    def _validate_cardinalities(
        cls,
        relation_type: DiagramRelationType,
        source_cardinality: DiagramCardinality | None,
        target_cardinality: DiagramCardinality | None,
    ) -> None:
        if relation_type == DiagramRelationType.ASSOCIATION:
            if source_cardinality is None or target_cardinality is None:
                raise InvalidDiagramRelationCardinalityException()
            try:
                DiagramCardinality(source_cardinality)
                DiagramCardinality(target_cardinality)
            except (ValueError, TypeError):
                raise InvalidDiagramRelationCardinalityException()
        else:
            if source_cardinality is not None or target_cardinality is not None:
                raise InvalidDiagramRelationCardinalityException()

    @classmethod
    def create(
        cls,
        id: UUID,
        project_id: UUID,
        source_class_id: UUID,
        target_class_id: UUID,
        relation_type: DiagramRelationType,
        source_handle: DiagramRelationHandle,
        target_handle: DiagramRelationHandle,
        name: str = "Nueva relación",
        source_cardinality: DiagramCardinality | None = None,
        target_cardinality: DiagramCardinality | None = None,
        bridge_class_id: UUID | None = None,
        bridge_handle: DiagramRelationHandle | None = None,
    ) -> "DiagramRelation":
        """Fábrica nombrada para crear una relación validando invariantes."""
        final_name = name
        if relation_type != DiagramRelationType.ASSOCIATION and (
            name is None or name == "Nueva relación"
        ):
            final_name = ""
        return cls(
            id=id,
            project_id=project_id,
            source_class_id=source_class_id,
            target_class_id=target_class_id,
            relation_type=relation_type,
            source_handle=source_handle,
            target_handle=target_handle,
            name=final_name,
            source_cardinality=source_cardinality,
            target_cardinality=target_cardinality,
            bridge_class_id=bridge_class_id,
            bridge_handle=bridge_handle,
        )

    def rename(self, new_name: str) -> None:
        """Actualiza el nombre de la relación. Solo las asociaciones admiten nombre."""
        if self.relation_type != DiagramRelationType.ASSOCIATION:
            raise NonAssociativeRelationNameCannotBeModifiedException()
        self._name = self._validate_name(new_name)
