from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    map_sqlite_type,
    sanitize_class_attributes,
    to_snake_case,
)
from app.modules.code_generation.application.services.generators.relation_resolver import (
    resolve_entity_dependencies,
    topological_sort_classes,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


class SqliteSchemaGenerator:
    """
    Generador de sentencias DDL para SQLite (schema.sql).
    Produce un script limpio para bases de datos locales/móviles (Flutter/SQLite)
    con afinidades de tipos SQLite, claves foráneas e índices.
    """

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(
        self,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto],
    ) -> GeneratedFile:
        all_classes_map: dict[UUID, DiagramClassSnapshotDto] = {
            c.id: c for c in classes
        }

        # 1. Ordenamiento topológico: tablas maestras antes que tablas dependientes
        ordered_classes = topological_sort_classes(classes, relations)

        sql_blocks: list[str] = [
            "-- ============================================================================",
            f"-- SQLite Schema for: {self.config.project_name}",
            "-- Generated automatically for Mobile Local-First / Flutter SQLite",
            "-- ============================================================================",
            "",
            "PRAGMA foreign_keys = ON;",
            "",
        ]

        for c in ordered_classes:
            table_name = to_snake_case(c.name)
            sanitized_attrs = sanitize_class_attributes(c.attributes)
            attr_by_orig_name = {a.name: a for a in c.attributes}

            column_defs: list[str] = []
            seen_columns: set[str] = set()

            # Atributos propios de la entidad
            for sa in sanitized_attrs:
                col_name = sa.column_name
                seen_columns.add(col_name)

                if sa.is_primary_key:
                    column_defs.append(f"    {col_name} TEXT PRIMARY KEY NOT NULL")
                    continue

                orig_attr = attr_by_orig_name.get(sa.original_name)
                raw_type = orig_attr.data_type if orig_attr else sa.java_type
                sqlite_type = map_sqlite_type(raw_type)

                constraints = []
                if not sa.is_nullable:
                    constraints.append("NOT NULL")

                # Default values si existen o se infieren
                name_lower = col_name.lower()
                if sa.is_nullable:
                    if sqlite_type == "INTEGER" and ("stock" in name_lower or "cantidad" in name_lower):
                        constraints.append("DEFAULT 0")
                    elif sqlite_type == "TEXT" and "fecha" in name_lower:
                        constraints.append("DEFAULT CURRENT_TIMESTAMP")

                clause = f"    {col_name} {sqlite_type}"
                if constraints:
                    clause += f" {' '.join(constraints)}"
                column_defs.append(clause)

            # Dependencias de claves foráneas legítimas
            deps = resolve_entity_dependencies(c, all_classes_map, relations)
            fk_constraints: list[str] = []
            indexes: list[str] = []

            for dep in deps:
                fk_col = dep.fk_column_name
                target_table = to_snake_case(dep.referenced_class_name)

                # Si la columna FK no estaba ya en los atributos de la clase, añadirla
                if fk_col not in seen_columns:
                    req_clause = " NOT NULL" if not dep.is_nullable else ""
                    column_defs.append(f"    {fk_col} TEXT{req_clause}")
                    seen_columns.add(fk_col)

                fk_constraints.append(
                    f"    FOREIGN KEY ({fk_col}) REFERENCES {target_table}(id) ON UPDATE CASCADE ON DELETE RESTRICT"
                )
                indexes.append(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{fk_col} ON {table_name}({fk_col});"
                )

            # Ensamblar sentencia CREATE TABLE
            all_table_lines = column_defs + fk_constraints
            table_body = ",\n".join(all_table_lines)

            sql_blocks.append(f"-- Table: {table_name}")
            sql_blocks.append(f"CREATE TABLE IF NOT EXISTS {table_name} (\n{table_body}\n);")
            sql_blocks.append("")

            # Índices de claves foráneas
            if indexes:
                for idx in indexes:
                    sql_blocks.append(idx)
                sql_blocks.append("")

        content = "\n".join(sql_blocks).strip() + "\n"

        return GeneratedFile(
            relative_path="schema.sql",
            content=content,
        )
