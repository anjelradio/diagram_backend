"""Caso de uso para importar un proyecto completo desde un archivo XMI/XML."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.modules.diagram.application.services.diagram_relation_materializer import (
    MaterializationStrategy,
    determine_materialization_plan,
)
from app.modules.diagram.domain.entities.diagram_attribute import (
    DiagramAttribute,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.entities.diagram_class import DiagramClass
from app.modules.diagram.domain.entities.diagram_relation import DiagramRelation
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
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
from app.modules.projects.application.services.xmi_project_importer import (
    XmiProjectImporter,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.repositories.project_repository import (
    ProjectRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class ImportProjectCommand:
    """Comando que encapsula los datos necesarios para importar un proyecto."""

    user_id: str
    xml_content: bytes | str


class ImportProjectUseCase:
    """Orquesta el parseo de XMI, la creación del proyecto y la persistencia atómica de su diagrama."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        diagram_class_repository: DiagramClassRepository,
        diagram_attribute_repository: DiagramAttributeRepository,
        diagram_relation_repository: DiagramRelationRepository,
        uow: UnitOfWorkPort,
        importer: XmiProjectImporter | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.diagram_class_repository = diagram_class_repository
        self.diagram_attribute_repository = diagram_attribute_repository
        self.diagram_relation_repository = diagram_relation_repository
        self.uow = uow
        self.importer = importer or XmiProjectImporter()

    def execute(self, command: ImportProjectCommand) -> UUID:
        """Parsea el archivo XMI y persiste el proyecto, clases, atributos y relaciones."""
        # 1. Parsear el archivo y validar estructura
        pkg = self.importer.parse(command.xml_content)

        # 2. Crear y guardar la entidad Project
        project = Project.create(
            owner_id=command.user_id,
            name=pkg.name[:255] if pkg.name else "Proyecto Importado",
        )
        self.project_repository.save(project)

        # 3. Crear y guardar clases y sus claves primarias
        ea_to_class: dict[str, DiagramClass] = {}
        class_attributes_map: dict[UUID, list[DiagramAttribute]] = {}

        for c_def in pkg.classes:
            class_id = uuid4()
            diagram_class = DiagramClass.create(
                id=class_id,
                project_id=project.id,
                name=c_def.name,
                position_x=c_def.position_x,
                position_y=c_def.position_y,
            )
            self.diagram_class_repository.save(diagram_class)
            ea_to_class[c_def.ea_id] = diagram_class

            # Crear clave primaria 'id' en posición 0
            pk_attr = DiagramAttribute.create_primary_key(
                id=uuid4(),
                class_id=class_id,
                name="id",
            )
            self.diagram_attribute_repository.save(pk_attr)
            class_attributes_map[class_id] = [pk_attr]

            # Crear atributos secundarios
            for idx, attr_def in enumerate(c_def.attributes, start=1):
                sec_attr = DiagramAttribute.create_secondary(
                    id=uuid4(),
                    class_id=class_id,
                    name=attr_def.parsed_name,
                    position=idx,
                    data_type=attr_def.data_type,
                    is_nullable=attr_def.is_nullable,
                )
                self.diagram_attribute_repository.save(sec_attr)
                class_attributes_map[class_id].append(sec_attr)

        # 4. Materializar y guardar relaciones UML
        for rel_def in pkg.relations:
            src_class = ea_to_class.get(rel_def.source_ea_id)
            tgt_class = ea_to_class.get(rel_def.target_ea_id)

            if not src_class or not tgt_class:
                continue

            if src_class.id == tgt_class.id and rel_def.relation_type != DiagramRelationType.ASSOCIATION:
                continue

            rel_id = uuid4()
            plan = determine_materialization_plan(
                relation_type=rel_def.relation_type,
                source_class_id=src_class.id,
                target_class_id=tgt_class.id,
                source_attributes_count=len(class_attributes_map[src_class.id]),
                target_attributes_count=len(class_attributes_map[tgt_class.id]),
                source_cardinality=rel_def.source_cardinality,
                target_cardinality=rel_def.target_cardinality,
            )

            bridge_class_id: UUID | None = None
            bridge_handle: DiagramRelationHandle | None = None
            fks_to_save: list[DiagramAttribute] = []

            if plan.strategy == MaterializationStrategy.FOREIGN_KEY and plan.foreign_key:
                fk_rule = plan.foreign_key
                ref_class = src_class if fk_rule.referenced_class_id == src_class.id else tgt_class
                receiving_attrs = class_attributes_map[fk_rule.receiving_class_id]
                existing_names = {a.name.lower() for a in receiving_attrs}
                base_fk_name = f"{ref_class.name.lower()}_id"
                fk_name = base_fk_name
                suffix = 2
                while fk_name in existing_names:
                    fk_name = f"{base_fk_name}_{suffix}"
                    suffix += 1

                fk_attr = DiagramAttribute(
                    id=uuid4(),
                    class_id=fk_rule.receiving_class_id,
                    name=fk_name,
                    data_type=DiagramAttributeDataType.UUID,
                    position=len(receiving_attrs),
                    is_primary_key=False,
                    is_nullable=fk_rule.is_nullable,
                    is_foreign_key=True,
                    referenced_class_id=fk_rule.referenced_class_id,
                    relation_id=rel_id,
                )
                fks_to_save.append(fk_attr)
                receiving_attrs.append(fk_attr)

            elif plan.strategy == MaterializationStrategy.BRIDGE_CLASS and plan.bridge_class:
                # Determinar si la clase intermedia ya existe en el modelo importado
                existing_bridge_class: DiagramClass | None = None
                if rel_def.bridge_ea_id and rel_def.bridge_ea_id in ea_to_class:
                    existing_bridge_class = ea_to_class[rel_def.bridge_ea_id]
                else:
                    expected_names = {
                        f"{src_class.name}_{tgt_class.name}".lower(),
                        f"{tgt_class.name}_{src_class.name}".lower(),
                        f"{src_class.name}{tgt_class.name}".lower(),
                        f"{tgt_class.name}{src_class.name}".lower(),
                        f"{src_class.name}relation".lower(),
                        f"{src_class.name}_relation".lower(),
                    }
                    for c_def in pkg.classes:
                        if c_def.name.lower() in expected_names and c_def.ea_id in ea_to_class:
                            existing_bridge_class = ea_to_class[c_def.ea_id]
                            break

                if existing_bridge_class is not None:
                    bridge_id = existing_bridge_class.id
                    bridge_class_id = bridge_id
                    bridge_handle = rel_def.bridge_handle or DiagramRelationHandle.TOP_CENTER

                    # Nombres canónicos de claves foráneas
                    if src_class.id == tgt_class.id:
                        clean_base = src_class.name.lower()
                        if clean_base.endswith("_id"):
                            clean_base = clean_base[:-3]
                        src_fk_name = f"{clean_base}_a_id"
                        tgt_fk_name = f"{clean_base}_b_id"
                    else:
                        src_fk_name = f"{src_class.name.lower()}_id"
                        tgt_fk_name = f"{tgt_class.name.lower()}_id"

                    # Asegurar claves foráneas requeridas y posición canónica en la clase puente existente
                    existing_attrs = class_attributes_map.get(bridge_id, [])
                    pk_attr = next((a for a in existing_attrs if a.is_primary_key), None)
                    business_attrs = [
                        a for a in existing_attrs
                        if not a.is_primary_key and not a.is_foreign_key
                        and a.name.lower() not in (src_fk_name, tgt_fk_name)
                    ]

                    # Reordenar atributos de negocio para que empiecen canónicamente en posición 3
                    for idx, b_attr in enumerate(business_attrs):
                        b_attr.compact_position(3 + idx)

                    attrs_to_reorder = ([pk_attr] if pk_attr else []) + business_attrs
                    if business_attrs:
                        self.diagram_attribute_repository.reorder_attributes(bridge_id, attrs_to_reorder)

                    # Crear o asignar fk_src en posición 1
                    existing_src_fk = next((a for a in existing_attrs if a.name.lower() == src_fk_name), None)
                    fk_src_id = existing_src_fk.id if existing_src_fk else uuid4()
                    fk_src = DiagramAttribute(
                        id=fk_src_id,
                        class_id=bridge_id,
                        name=src_fk_name,
                        data_type=DiagramAttributeDataType.UUID,
                        position=1,
                        is_primary_key=False,
                        is_nullable=False,
                        is_foreign_key=True,
                        referenced_class_id=src_class.id,
                        relation_id=rel_id,
                    )
                    fks_to_save.append(fk_src)

                    # Crear o asignar fk_tgt en posición 2
                    existing_tgt_fk = next((a for a in existing_attrs if a.name.lower() == tgt_fk_name), None)
                    fk_tgt_id = existing_tgt_fk.id if existing_tgt_fk else uuid4()
                    fk_tgt = DiagramAttribute(
                        id=fk_tgt_id,
                        class_id=bridge_id,
                        name=tgt_fk_name,
                        data_type=DiagramAttributeDataType.UUID,
                        position=2,
                        is_primary_key=False,
                        is_nullable=False,
                        is_foreign_key=True,
                        referenced_class_id=tgt_class.id,
                        relation_id=rel_id,
                    )
                    fks_to_save.append(fk_tgt)

                    class_attributes_map[bridge_id] = (
                        ([pk_attr] if pk_attr else [])
                        + [fk_src, fk_tgt]
                        + business_attrs
                    )
                else:
                    bridge_id = uuid4()
                    bridge_name = (
                        f"{src_class.name}_{tgt_class.name}"
                        if src_class.id != tgt_class.id
                        else f"{src_class.name}Relation"
                    )
                    bridge_x = (src_class.position_x + tgt_class.position_x) / 2
                    bridge_y = ((src_class.position_y + tgt_class.position_y) / 2) + 120

                    bridge_class = DiagramClass.create(
                        id=bridge_id,
                        project_id=project.id,
                        name=bridge_name,
                        position_x=bridge_x,
                        position_y=bridge_y,
                    )
                    self.diagram_class_repository.save(bridge_class)

                    bridge_pk = DiagramAttribute.create_primary_key(
                        id=uuid4(),
                        class_id=bridge_id,
                        name="id",
                    )
                    self.diagram_attribute_repository.save(bridge_pk)

                    # Nombres canónicos de claves foráneas
                    if src_class.id == tgt_class.id:
                        clean_base = src_class.name.lower()
                        if clean_base.endswith("_id"):
                            clean_base = clean_base[:-3]
                        fk_src_name = f"{clean_base}_a_id"
                        fk_tgt_name = f"{clean_base}_b_id"
                    else:
                        fk_src_name = f"{src_class.name.lower()}_id"
                        fk_tgt_name = f"{tgt_class.name.lower()}_id"

                    # Claves foráneas en la clase puente
                    fk_src = DiagramAttribute(
                        id=uuid4(),
                        class_id=bridge_id,
                        name=fk_src_name,
                        data_type=DiagramAttributeDataType.UUID,
                        position=1,
                        is_primary_key=False,
                        is_nullable=False,
                        is_foreign_key=True,
                        referenced_class_id=src_class.id,
                        relation_id=rel_id,
                    )
                    fks_to_save.append(fk_src)

                    fk_tgt = DiagramAttribute(
                        id=uuid4(),
                        class_id=bridge_id,
                        name=fk_tgt_name,
                        data_type=DiagramAttributeDataType.UUID,
                        position=2,
                        is_primary_key=False,
                        is_nullable=False,
                        is_foreign_key=True,
                        referenced_class_id=tgt_class.id,
                        relation_id=rel_id,
                    )
                    fks_to_save.append(fk_tgt)

                    bridge_class_id = bridge_id
                    bridge_handle = rel_def.bridge_handle or DiagramRelationHandle.TOP_CENTER
                    class_attributes_map[bridge_id] = [bridge_pk, fk_src, fk_tgt]

            elif plan.strategy == MaterializationStrategy.SHARED_PRIMARY_KEY and plan.shared_primary_key:
                spk_rule = plan.shared_primary_key
                subclass_attrs = class_attributes_map.get(spk_rule.subclass_id, [])
                subclass_pk = next((a for a in subclass_attrs if a.is_primary_key), None)
                if subclass_pk:
                    subclass_pk.as_shared_primary_key(
                        referenced_class_id=spk_rule.superclass_id,
                        relation_id=rel_id,
                    )
                    fks_to_save.append(subclass_pk)

            # Asegurar que las relaciones no asociativas ignoren cualquier nombre y conserven cardinalidades nulas
            is_assoc = rel_def.relation_type == DiagramRelationType.ASSOCIATION
            final_name = rel_def.name if is_assoc else ""
            final_src_card = rel_def.source_cardinality if is_assoc else None
            final_tgt_card = rel_def.target_cardinality if is_assoc else None

            # Crear y guardar la relación de diagrama primero para satisfacer la FK en BD
            relation = DiagramRelation(
                id=rel_id,
                project_id=project.id,
                source_class_id=src_class.id,
                target_class_id=tgt_class.id,
                relation_type=rel_def.relation_type,
                source_handle=rel_def.source_handle,
                target_handle=rel_def.target_handle,
                name=final_name,
                source_cardinality=final_src_card,
                target_cardinality=final_tgt_card,
                bridge_class_id=bridge_class_id,
                bridge_handle=bridge_handle,
            )
            self.diagram_relation_repository.save(relation)

            # Guardar atributos foráneos una vez que la relación ya existe
            for fk in fks_to_save:
                self.diagram_attribute_repository.save(fk)

        # 5. Confirmar transacción atómica
        self.uow.commit()

        return project.id
