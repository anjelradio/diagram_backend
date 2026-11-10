from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.diagram.domain.repositories.diagram_attribute_repository import (
    DiagramAttributeRepository,
)
from app.modules.diagram.domain.repositories.diagram_class_repository import (
    DiagramClassRepository,
)
from app.modules.diagram.domain.repositories.diagram_relation_repository import (
    DiagramRelationRepository,
)
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


@dataclass(frozen=True, slots=True)
class NotionProjectFullSnapshot:
    """Snapshot completo y estructurado de un proyecto para alimentar la inicialización en Notion."""

    project_id: UUID
    project_name: str
    owner_name: str
    collaborator_names: list[str]
    classes: list[dict[str, Any]]
    relations: list[dict[str, Any]]


class NotionProjectSnapshotBuilder:
    """Reúne en lote el nombre del proyecto, colaboradores activos y todo el diagrama (clases, atributos y relaciones)."""

    def __init__(
        self,
        session: Session,
        project_repository: ProjectRepository,
        class_repository: DiagramClassRepository,
        attribute_repository: DiagramAttributeRepository,
        relation_repository: DiagramRelationRepository,
    ) -> None:
        self.session = session
        self.project_repository = project_repository
        self.class_repository = class_repository
        self.attribute_repository = attribute_repository
        self.relation_repository = relation_repository

    def build_snapshot(self, project_id: UUID) -> NotionProjectFullSnapshot:
        project = self.project_repository.find_by_id(project_id)
        project_name = project.name if project is not None else "Proyecto de Diagrama"
        owner_id = project.owner_id if project is not None else ""

        # 1. Resolver colaboradores activos
        members_stmt = select(ProjectMemberModel.user_id).where(
            ProjectMemberModel.project_id == project_id,
            ProjectMemberModel.deleted_date.is_(None),
        )
        member_user_ids = set(self.session.exec(members_stmt).all())
        all_user_ids = {owner_id, *member_user_ids} if owner_id else member_user_ids

        users_stmt = select(BetterAuthUser.id, BetterAuthUser.name).where(
            BetterAuthUser.id.in_(all_user_ids)
        )
        user_names_map = {uid: name for uid, name in self.session.exec(users_stmt).all() if name}

        owner_name = user_names_map.get(owner_id, "Propietario")
        collaborator_names = [
            user_names_map.get(uid, f"Colaborador {uid[:6]}")
            for uid in sorted(all_user_ids)
            if uid in user_names_map
        ]
        if not collaborator_names:
            collaborator_names = [owner_name]

        # 2. Recopilar clases y atributos
        classes_data: list[dict[str, Any]] = []
        classes = self.class_repository.list_by_project_id(project_id)
        class_names_by_id: dict[UUID, str] = {c.id: c.name for c in classes}

        for c in classes:
            attrs = self.attribute_repository.list_by_class_id(c.id)
            attr_summaries = []
            for a in attrs:
                pk_flag = " [PK]" if a.is_primary_key else ""
                fk_flag = " [FK]" if a.is_foreign_key else ""
                null_flag = " (opcional)" if a.is_nullable else ""
                attr_summaries.append(f"{a.name}: {a.data_type.value}{pk_flag}{fk_flag}{null_flag}")
            classes_data.append({
                "id": str(c.id),
                "name": c.name,
                "attributes": attr_summaries,
            })

        # 3. Recopilar relaciones
        relations_data: list[dict[str, Any]] = []
        relations = self.relation_repository.list_by_project_id(project_id)
        for r in relations:
            src_name = class_names_by_id.get(r.source_class_id, "Desconocida")
            tgt_name = class_names_by_id.get(r.target_class_id, "Desconocida")
            relations_data.append({
                "id": str(r.id),
                "name": r.name,
                "relation_type": r.relation_type.value,
                "source_class": src_name,
                "target_class": tgt_name,
                "source_cardinality": r.source_cardinality.value if r.source_cardinality else None,
                "target_cardinality": r.target_cardinality.value if r.target_cardinality else None,
            })

        return NotionProjectFullSnapshot(
            project_id=project_id,
            project_name=project_name,
            owner_name=owner_name,
            collaborator_names=collaborator_names,
            classes=classes_data,
            relations=relations_data,
        )
