"""Persistencia SQLModel de consultas selectivas para el agente."""

from uuid import UUID

from sqlalchemy import func, union_all
from sqlmodel import Session, select

from app.modules.diagram.application.ports.readers.agent_diagram_reader import (
    AgentDiagramReader,
    DiagramElementDetailDto,
    DiagramElementReferenceDto,
    DiagramElementSearchDto,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)


class SQLModelAgentDiagramReader(AgentDiagramReader):
    """Reader con límite de filas y filtros explícitos por proyecto."""

    _ALLOWED_TYPES = {"class", "attribute", "relation"}

    def __init__(self, session: Session, *, max_detail_items: int = 20) -> None:
        if max_detail_items < 1:
            raise ValueError("El límite de detalle debe ser positivo.")
        self.session = session
        self.max_detail_items = max_detail_items

    def search_elements(
        self,
        *,
        project_id: UUID,
        query: str,
        types: tuple[str, ...],
        limit: int,
        offset: int,
    ) -> DiagramElementSearchDto:
        requested_types = tuple(kind for kind in types if kind in self._ALLOWED_TYPES)
        if not requested_types:
            requested_types = ("class", "attribute", "relation")
        search_term = f"%{query}%"
        candidates: list[DiagramElementReferenceDto] = []
        per_type_limit = limit + offset + 1

        if "class" in requested_types:
            rows = self.session.exec(
                select(DiagramClassModel.id, DiagramClassModel.name)
                .where(
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.name.ilike(search_term),
                    DiagramClassModel.deleted_date.is_(None),
                )
                .order_by(DiagramClassModel.name.asc(), DiagramClassModel.id.asc())
                .limit(per_type_limit)
            ).all()
            candidates.extend(
                DiagramElementReferenceDto("class", element_id, name)
                for element_id, name in rows
            )

        if "attribute" in requested_types:
            rows = self.session.exec(
                select(DiagramAttributeModel.id, DiagramAttributeModel.name, DiagramAttributeModel.class_id)
                .join(DiagramClassModel, DiagramClassModel.id == DiagramAttributeModel.class_id)
                .where(
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.deleted_date.is_(None),
                    DiagramAttributeModel.deleted_date.is_(None),
                    DiagramAttributeModel.name.ilike(search_term),
                )
                .order_by(DiagramAttributeModel.name.asc(), DiagramAttributeModel.id.asc())
                .limit(per_type_limit)
            ).all()
            candidates.extend(
                DiagramElementReferenceDto("attribute", element_id, name, class_id)
                for element_id, name, class_id in rows
            )

        if "relation" in requested_types:
            rows = self.session.exec(
                select(DiagramRelationModel.id, DiagramRelationModel.name)
                .where(
                    DiagramRelationModel.project_id == project_id,
                    DiagramRelationModel.deleted_date.is_(None),
                    DiagramRelationModel.name.ilike(search_term),
                )
                .order_by(DiagramRelationModel.name.asc(), DiagramRelationModel.id.asc())
                .limit(per_type_limit)
            ).all()
            candidates.extend(
                DiagramElementReferenceDto("relation", element_id, name)
                for element_id, name in rows
            )

        candidates.sort(key=lambda item: (item.element_type, item.name.casefold(), str(item.id)))
        visible_items = tuple(candidates[offset : offset + limit])
        has_more = len(candidates) > offset + limit
        ambiguous_names = self._find_ambiguous_names(
            project_id=project_id,
            types=requested_types,
            names=tuple({item.name.lower() for item in visible_items}),
        )
        return DiagramElementSearchDto(
            items=visible_items,
            has_more=has_more,
            next_offset=offset + len(visible_items) if has_more else None,
            ambiguous_names=ambiguous_names,
        )

    def _find_ambiguous_names(
        self,
        *,
        project_id: UUID,
        types: tuple[str, ...],
        names: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Cuenta duplicados de los nombres visibles sobre todas las coincidencias."""
        if not names:
            return ()

        name_queries = []
        if "class" in types:
            name_queries.append(
                select(func.lower(DiagramClassModel.name).label("element_name")).where(
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.deleted_date.is_(None),
                    func.lower(DiagramClassModel.name).in_(names),
                )
            )
        if "attribute" in types:
            name_queries.append(
                select(func.lower(DiagramAttributeModel.name).label("element_name"))
                .join(DiagramClassModel, DiagramClassModel.id == DiagramAttributeModel.class_id)
                .where(
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.deleted_date.is_(None),
                    DiagramAttributeModel.deleted_date.is_(None),
                    func.lower(DiagramAttributeModel.name).in_(names),
                )
            )
        if "relation" in types:
            name_queries.append(
                select(func.lower(DiagramRelationModel.name).label("element_name")).where(
                    DiagramRelationModel.project_id == project_id,
                    DiagramRelationModel.deleted_date.is_(None),
                    func.lower(DiagramRelationModel.name).in_(names),
                )
            )
        if len(name_queries) < 2:
            if not name_queries:
                return ()
            all_names = name_queries[0].subquery("project_element_names")
        else:
            all_names = union_all(*name_queries).subquery("project_element_names")

        statement = (
            select(all_names.c.element_name)
            .group_by(all_names.c.element_name)
            .having(func.count() > 1)
        )
        return tuple(self.session.exec(statement).all())

    def get_element(
        self, *, project_id: UUID, element_type: str, element_id: UUID
    ) -> DiagramElementDetailDto | None:
        if element_type == "class":
            class_model = self.session.exec(
                select(DiagramClassModel).where(
                    DiagramClassModel.id == element_id,
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.deleted_date.is_(None),
                )
            ).first()
            if class_model is None:
                return None
            attribute_rows = self.session.exec(
                select(DiagramAttributeModel)
                .where(
                    DiagramAttributeModel.class_id == element_id,
                    DiagramAttributeModel.deleted_date.is_(None),
                )
                .order_by(DiagramAttributeModel.position.asc(), DiagramAttributeModel.id.asc())
                .limit(self.max_detail_items + 1)
            ).all()
            attributes_truncated = len(attribute_rows) > self.max_detail_items
            attributes = attribute_rows[: self.max_detail_items]
            relation_rows = self.session.exec(
                select(DiagramRelationModel).where(
                    DiagramRelationModel.project_id == project_id,
                    DiagramRelationModel.deleted_date.is_(None),
                    (DiagramRelationModel.source_class_id == element_id)
                    | (DiagramRelationModel.target_class_id == element_id)
                    | (DiagramRelationModel.bridge_class_id == element_id),
                )
                .order_by(DiagramRelationModel.name.asc(), DiagramRelationModel.id.asc())
                .limit(self.max_detail_items + 1)
            ).all()
            relations_truncated = len(relation_rows) > self.max_detail_items
            relations = relation_rows[: self.max_detail_items]
            return DiagramElementDetailDto(
                "class",
                class_model.id,
                class_model.name,
                {
                    "position_x": class_model.position_x,
                    "position_y": class_model.position_y,
                    "attributes": [
                        {
                            "id": str(attribute.id),
                            "name": attribute.name,
                            "data_type": attribute.data_type,
                            "position": attribute.position,
                            "is_primary_key": attribute.is_primary_key,
                            "is_foreign_key": attribute.is_foreign_key,
                            "is_nullable": attribute.is_nullable,
                            "referenced_class_id": str(attribute.referenced_class_id)
                            if attribute.referenced_class_id
                            else None,
                            "relation_id": str(attribute.relation_id)
                            if attribute.relation_id
                            else None,
                        }
                        for attribute in attributes
                    ],
                    "attributes_truncated": attributes_truncated,
                    "relations": [
                        self._relation_summary(relation, include_derived_attributes=False)
                        for relation in relations
                    ],
                    "relations_truncated": relations_truncated,
                },
            )

        if element_type == "attribute":
            row = self.session.exec(
                select(DiagramAttributeModel, DiagramClassModel)
                .join(DiagramClassModel, DiagramClassModel.id == DiagramAttributeModel.class_id)
                .where(
                    DiagramAttributeModel.id == element_id,
                    DiagramAttributeModel.deleted_date.is_(None),
                    DiagramClassModel.project_id == project_id,
                    DiagramClassModel.deleted_date.is_(None),
                )
            ).first()
            if row is None:
                return None
            attribute, owner = row
            return DiagramElementDetailDto(
                "attribute",
                attribute.id,
                attribute.name,
                {
                    "class_id": str(owner.id),
                    "class_name": owner.name,
                    "data_type": attribute.data_type,
                    "position": attribute.position,
                    "is_primary_key": attribute.is_primary_key,
                    "is_foreign_key": attribute.is_foreign_key,
                    "is_nullable": attribute.is_nullable,
                    "referenced_class_id": str(attribute.referenced_class_id)
                    if attribute.referenced_class_id
                    else None,
                    "relation_id": str(attribute.relation_id) if attribute.relation_id else None,
                },
            )

        if element_type == "relation":
            relation = self.session.exec(
                select(DiagramRelationModel).where(
                    DiagramRelationModel.id == element_id,
                    DiagramRelationModel.project_id == project_id,
                    DiagramRelationModel.deleted_date.is_(None),
                )
            ).first()
            if relation is None:
                return None
            derived_rows = self.session.exec(
                select(DiagramAttributeModel).where(
                    DiagramAttributeModel.relation_id == relation.id,
                    DiagramAttributeModel.deleted_date.is_(None),
                ).order_by(
                    DiagramAttributeModel.position.asc(), DiagramAttributeModel.id.asc()
                ).limit(self.max_detail_items + 1)
            ).all()
            derived_attributes_truncated = len(derived_rows) > self.max_detail_items
            derived_attributes = derived_rows[: self.max_detail_items]
            return DiagramElementDetailDto(
                "relation",
                relation.id,
                relation.name,
                self._relation_summary(
                    relation,
                    derived_attributes,
                    derived_attributes_truncated=derived_attributes_truncated,
                ),
            )
        return None

    @staticmethod
    def _relation_summary(
        relation: DiagramRelationModel,
        derived_attributes: list[DiagramAttributeModel] | None = None,
        *,
        include_derived_attributes: bool = True,
        derived_attributes_truncated: bool = False,
    ) -> dict[str, object]:
        materialization: dict[str, object] = {
            "bridge_class_id": str(relation.bridge_class_id)
            if relation.bridge_class_id
            else None,
        }
        if include_derived_attributes:
            materialization["derived_attributes"] = [
                {
                    "id": str(attribute.id),
                    "class_id": str(attribute.class_id),
                    "name": attribute.name,
                    "is_primary_key": attribute.is_primary_key,
                    "is_foreign_key": attribute.is_foreign_key,
                    "referenced_class_id": str(attribute.referenced_class_id)
                    if attribute.referenced_class_id
                    else None,
                }
                for attribute in (derived_attributes or [])
            ]
            materialization["derived_attributes_truncated"] = derived_attributes_truncated
        return {
            "relation_type": relation.relation_type,
            "source_class_id": str(relation.source_class_id),
            "source_handle": relation.source_handle,
            "source_cardinality": relation.source_cardinality,
            "target_class_id": str(relation.target_class_id),
            "target_handle": relation.target_handle,
            "target_cardinality": relation.target_cardinality,
            "bridge_class_id": str(relation.bridge_class_id)
            if relation.bridge_class_id
            else None,
            "bridge_handle": relation.bridge_handle,
            "materialization": materialization,
        }
