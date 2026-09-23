from dataclasses import dataclass
from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    to_camel_case,
    to_pascal_case,
    to_snake_case,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


@dataclass(frozen=True, slots=True)
class EntityRelationDependency:
    """Representa una dependencia de llave foránea (ManyToOne) legítima hacia otra entidad."""

    referenced_class_id: UUID
    referenced_class_name: str
    field_name: str
    fk_field_name: str
    fk_column_name: str
    method_suffix: str
    fk_method_suffix: str
    repo_name: str
    repo_var: str
    label: str
    is_nullable: bool


def is_many_to_many_relation(rel: DiagramRelationSnapshotDto) -> bool:
    """
    Determina si una relación es de Muchos a Muchos (N:M).
    En N:M, ni el origen ni el destino reciben llaves foráneas; estas pertenecen
    exclusivamente a la entidad puente intermedia.
    """
    if rel.bridge is not None:
        return True
    source_many = rel.source_cardinality in ("0..*", "1..*", "*")
    target_many = rel.target_cardinality in ("0..*", "1..*", "*")
    return bool(source_many and target_many)


def _build_dependency(
    referenced_class: DiagramClassSnapshotDto, is_nullable: bool = False
) -> EntityRelationDependency:
    pascal = to_pascal_case(referenced_class.name)
    camel = to_camel_case(referenced_class.name)
    snake = to_snake_case(referenced_class.name)

    return EntityRelationDependency(
        referenced_class_id=referenced_class.id,
        referenced_class_name=pascal,
        field_name=camel,
        fk_field_name=f"{camel}Id",
        fk_column_name=f"{snake}_id",
        method_suffix=pascal,
        fk_method_suffix=f"{pascal}Id",
        repo_name=f"{pascal}Repository",
        repo_var=f"{camel}Repository",
        label=referenced_class.name,
        is_nullable=is_nullable,
    )


def resolve_entity_dependencies(
    class_dto: DiagramClassSnapshotDto,
    all_classes: dict[UUID, DiagramClassSnapshotDto],
    relations: list[DiagramRelationSnapshotDto] | None = None,
) -> list[EntityRelationDependency]:
    """
    Resuelve con precisión las dependencias ManyToOne legítimas para una entidad de destino.

    Reglas:
    1. Si una relación es Muchos a Muchos (N:M):
       - Si class_dto es la clase puente intermedia: depende tanto del source como del target.
       - Si class_dto es participante principal (ej. Producto, Venta, Compra): NO recibe ninguna FK.
    2. Si una relación es 1:N o N:1:
       - El extremo receptor (Muchos) recibe la FK hacia el extremo referenciado (Uno).
    3. Si la clase tiene atributos explícitos con is_foreign_key=True y referenced_class_id:
       - Se garantiza la inclusión de la entidad referenciada y su nulabilidad exacta.
    """
    dependencies: dict[UUID, EntityRelationDependency] = {}
    relations = relations or []

    # 1. Procesar relaciones UML
    for rel in relations:
        if is_many_to_many_relation(rel):
            # Solo la clase puente intermedia recibe las llaves foráneas
            if rel.bridge is not None and rel.bridge.class_id == class_dto.id:
                src = all_classes.get(rel.source.class_id)
                tgt = all_classes.get(rel.target.class_id)
                if src and src.id != class_dto.id:
                    dependencies[src.id] = _build_dependency(src, is_nullable=False)
                if tgt and tgt.id != class_dto.id:
                    dependencies[tgt.id] = _build_dependency(tgt, is_nullable=False)
            # Para los extremos principales de N:M (ej. Producto con Venta o Compra),
            # NUNCA se agregan llaves foráneas.
            continue

        # Relaciones 1:N, 1:1, Agregación, Composición, etc.
        rel_type = (rel.relation_type or "").upper()
        if rel_type == "GENERALIZATION":
            continue

        receiving_id: UUID | None = None
        referenced_id: UUID | None = None
        is_nullable: bool = False

        if rel_type in ("AGGREGATION", "COMPOSITION"):
            receiving_id = rel.target.class_id
            referenced_id = rel.source.class_id
            is_nullable = (rel_type == "AGGREGATION")
        elif rel_type in ("REALIZATION", "DEPENDENCY"):
            receiving_id = rel.source.class_id
            referenced_id = rel.target.class_id
            is_nullable = (rel_type == "DEPENDENCY")
        else:
            # ASSOCIATION u otro
            source_many = rel.source_cardinality in ("0..*", "1..*", "*")
            target_many = rel.target_cardinality in ("0..*", "1..*", "*")

            if source_many and not target_many:
                receiving_id = rel.source.class_id
                referenced_id = rel.target.class_id
                is_nullable = rel.target_cardinality in ("0..1", None)
            elif target_many and not source_many:
                receiving_id = rel.target.class_id
                referenced_id = rel.source.class_id
                is_nullable = rel.source_cardinality in ("0..1", None)
            else:
                receiving_id = rel.target.class_id
                referenced_id = rel.source.class_id
                is_nullable = rel.source_cardinality in ("0..1", None)

        if receiving_id == class_dto.id and referenced_id and referenced_id != class_dto.id:
            ref_class = all_classes.get(referenced_id)
            if ref_class:
                dependencies[referenced_id] = _build_dependency(ref_class, is_nullable=is_nullable)

    # 2. Reconciliar con atributos explícitos de la clase
    for attr in class_dto.attributes:
        if attr.is_foreign_key and attr.referenced_class_id:
            ref_class = all_classes.get(attr.referenced_class_id)
            if ref_class and ref_class.id != class_dto.id:
                dependencies[ref_class.id] = _build_dependency(
                    ref_class, is_nullable=attr.is_nullable
                )
        elif not attr.is_primary_key:
            # Detección por convención de nombre si coincide con alguna clase
            attr_lower = attr.name.lower().replace("_", "").replace("-", "")
            for ref_id, ref_cls in all_classes.items():
                if ref_id == class_dto.id:
                    continue
                cls_lower = ref_cls.name.lower().replace("_", "").replace("-", "")
                if attr_lower in (f"{cls_lower}id", f"id{cls_lower}"):
                    if ref_id not in dependencies:
                        dependencies[ref_id] = _build_dependency(
                            ref_cls, is_nullable=attr.is_nullable
                        )
                    break

    return list(dependencies.values())


def topological_sort_classes(
    classes: list[DiagramClassSnapshotDto],
    relations: list[DiagramRelationSnapshotDto] | None = None,
) -> list[DiagramClassSnapshotDto]:
    """
    Ordena las clases topológicamente según sus dependencias de llaves foráneas.
    Las tablas maestras (sin dependencias) van primero (ej. Categoria, Venta).
    Las tablas dependientes (ej. Producto) van después de sus dependencias.
    Las tablas intermedias/puente de Muchos a Muchos (ej. VentaProducto) van al final.
    Si existen dependencias circulares, preserva las clases no resueltas al final de forma determinista.
    """
    if not classes:
        return []

    all_classes_map: dict[UUID, DiagramClassSnapshotDto] = {c.id: c for c in classes}
    relations = relations or []

    # Grafo de dependencias: clase_id -> conjunto de clases de las que depende
    deps_map: dict[UUID, set[UUID]] = {}
    for c in classes:
        deps = resolve_entity_dependencies(c, all_classes_map, relations)
        deps_map[c.id] = {
            d.referenced_class_id
            for d in deps
            if d.referenced_class_id in all_classes_map and d.referenced_class_id != c.id
        }

    sorted_classes: list[DiagramClassSnapshotDto] = []
    visited: set[UUID] = set()

    # Resolución iterativa por niveles (Kahn)
    while len(visited) < len(classes):
        ready = [
            c for c in classes
            if c.id not in visited and deps_map[c.id].issubset(visited)
        ]
        if not ready:
            # Si hay ciclos, agregar las restantes ordenadas por nombre
            remaining = [c for c in classes if c.id not in visited]
            remaining.sort(key=lambda x: x.name)
            sorted_classes.extend(remaining)
            break

        ready.sort(key=lambda x: x.name)
        for c in ready:
            visited.add(c.id)
            sorted_classes.append(c)

    return sorted_classes
