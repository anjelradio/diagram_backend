from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    to_snake_case,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)


@dataclass(frozen=True)
class PostgresColumn:
    name: str
    data_type: str
    is_primary_key: bool = False
    is_nullable: bool = True
    default_value: str | None = None
    attribute_id: UUID | None = None


@dataclass(frozen=True)
class PostgresForeignKey:
    name: str
    column_name: str
    foreign_table_name: str
    foreign_column_name: str
    on_delete: str = "CASCADE"
    on_update: str = "CASCADE"
    relation_id: UUID | None = None


@dataclass(frozen=True)
class PostgresTable:
    name: str
    class_id: UUID | None
    class_name: str
    columns: list[PostgresColumn]
    primary_keys: list[str]
    foreign_keys: list[PostgresForeignKey] = field(default_factory=list)
    indices: list[str] = field(default_factory=list)

    @property
    def columns_by_name(self) -> dict[str, PostgresColumn]:
        return {col.name: col for col in self.columns}


@dataclass(frozen=True)
class DesiredPostgresSchema:
    tables: list[PostgresTable]

    @property
    def tables_by_name(self) -> dict[str, PostgresTable]:
        return {tbl.name: tbl for tbl in self.tables}


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    val = getattr(obj, key, None)
    if val is not None:
        return val
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def map_data_type_to_postgres(raw_type: Any, is_pk: bool = False) -> str:
    """Mapea tipos de datos UML / DiagramAttributeDataType a tipos nativos de PostgreSQL."""
    if not raw_type:
        return "UUID" if is_pk else "VARCHAR(255)"

    type_str = str(raw_type).strip().upper()
    if type_str.startswith("DIAGRAMATTRIBUTEDATATYPE."):
        type_str = type_str.split(".", 1)[1]

    if type_str in ("UUID", "GUID"):
        return "UUID"
    if type_str in ("TEXT", "STRING", "STR", "VARCHAR", "CHAR"):
        return "TEXT" if type_str == "TEXT" else "VARCHAR(255)"
    if type_str in ("INTEGER", "INT", "SMALLINT", "SERIAL"):
        return "INTEGER"
    if type_str in ("BIGINT", "LONG", "BIGSERIAL"):
        return "BIGINT"
    if type_str in ("DECIMAL", "NUMERIC"):
        return "NUMERIC(12, 2)"
    if type_str in ("FLOAT", "DOUBLE", "REAL", "DOUBLE PRECISION"):
        return "DOUBLE PRECISION"
    if type_str in ("BOOLEAN", "BOOL"):
        return "BOOLEAN"
    if type_str in ("DATE",):
        return "DATE"
    if type_str in ("TIMESTAMP", "DATETIME", "TIMESTAMPTZ"):
        return "TIMESTAMPTZ"

    return "VARCHAR(255)"


class PostgresTargetSchemaBuilder:
    """Construye el esquema deseado de PostgreSQL a partir del diagrama UML."""

    @classmethod
    def build(
        cls,
        classes: list[Any],
        relations: list[Any] | None = None,
        attributes_by_class: dict[UUID, list[Any]] | None = None,
    ) -> DesiredPostgresSchema:
        relations = relations or []
        attrs_map = attributes_by_class or {}

        # Mapeo de class_id -> info de clase
        classes_by_id: dict[UUID, Any] = {}
        table_name_by_class_id: dict[UUID, str] = {}
        for c in classes:
            c_id = _get_val(c, "id")
            if isinstance(c_id, str):
                c_id = UUID(c_id)
            c_name = _get_val(c, "name", "")
            classes_by_id[c_id] = c
            table_name_by_class_id[c_id] = to_snake_case(str(c_name).strip())

        # Construir tablas individuales
        tables_map: dict[str, PostgresTable] = {}
        dependencies: dict[str, set[str]] = {tbl: set() for tbl in table_name_by_class_id.values()}

        for c in classes:
            c_id = _get_val(c, "id")
            if isinstance(c_id, str):
                c_id = UUID(c_id)
            c_name = str(_get_val(c, "name", "")).strip()
            tbl_name = table_name_by_class_id[c_id]

            attrs = attrs_map.get(c_id)
            if attrs is None:
                attrs = _get_val(c, "attributes", [])
            attrs = attrs or []

            columns: list[PostgresColumn] = []
            pks: list[str] = []
            fks: list[PostgresForeignKey] = []
            indices: list[str] = []

            # 1. Atributos propios de la clase
            for a in attrs:
                a_id = _get_val(a, "id")
                if isinstance(a_id, str):
                    a_id = UUID(a_id)
                a_name = str(_get_val(a, "name", "")).strip()
                col_name = to_snake_case(a_name)
                is_pk = bool(_get_val(a, "is_primary_key", False))
                is_nullable = bool(_get_val(a, "is_nullable", True))
                if is_pk:
                    is_nullable = False

                raw_type = _get_val(a, "data_type")
                pg_type = map_data_type_to_postgres(raw_type, is_pk=is_pk)
                default_val = "gen_random_uuid()" if is_pk and pg_type == "UUID" else None

                columns.append(
                    PostgresColumn(
                        name=col_name,
                        data_type=pg_type,
                        is_primary_key=is_pk,
                        is_nullable=is_nullable,
                        default_value=default_val,
                        attribute_id=a_id,
                    )
                )
                if is_pk:
                    pks.append(col_name)

                # Si es FK registrada explícitamente en el atributo
                is_fk = bool(_get_val(a, "is_foreign_key", False))
                ref_cls_id = _get_val(a, "referenced_class_id")
                if is_fk and ref_cls_id and UUID(str(ref_cls_id)) in table_name_by_class_id:
                    target_tbl = table_name_by_class_id[UUID(str(ref_cls_id))]
                    fk_name = f"fk_{tbl_name}_{col_name}"
                    fks.append(
                        PostgresForeignKey(
                            name=fk_name,
                            column_name=col_name,
                            foreign_table_name=target_tbl,
                            foreign_column_name="id",
                        )
                    )
                    indices.append(f"idx_{tbl_name}_{col_name}")
                    if target_tbl != tbl_name:
                        dependencies[tbl_name].add(target_tbl)

            # Si la clase no tenía PK explícita, asegurar PK id UUID por defecto
            if not pks:
                id_col = PostgresColumn(
                    name="id",
                    data_type="UUID",
                    is_primary_key=True,
                    is_nullable=False,
                    default_value="gen_random_uuid()",
                )
                columns.insert(0, id_col)
                pks.append("id")

            tables_map[tbl_name] = PostgresTable(
                name=tbl_name,
                class_id=c_id,
                class_name=c_name,
                columns=columns,
                primary_keys=pks,
                foreign_keys=fks,
                indices=indices,
            )

        # 2. Relaciones del diagrama que aún no estén materializadas como atributos
        junction_tables: list[PostgresTable] = []

        for rel in relations:
            rel_id = _get_val(rel, "id")
            if isinstance(rel_id, str):
                rel_id = UUID(rel_id)
            src_id = _get_val(rel, "source_class_id")
            if isinstance(src_id, str):
                src_id = UUID(src_id)
            tgt_id = _get_val(rel, "target_class_id")
            if isinstance(tgt_id, str):
                tgt_id = UUID(tgt_id)
            rel_type = str(_get_val(rel, "relation_type", "")).upper()

            if src_id not in table_name_by_class_id or tgt_id not in table_name_by_class_id:
                continue

            src_tbl = table_name_by_class_id[src_id]
            tgt_tbl = table_name_by_class_id[tgt_id]

            if rel_type == "GENERALIZATION":
                # En herencia: src es subclase, tgt es superclase.
                # La tabla de la subclase tiene FK en su PK hacia la superclase
                sub_table = tables_map.get(src_tbl)
                if sub_table:
                    fk_name = f"fk_{src_tbl}_inherits_{tgt_tbl}"
                    if not any(f.name == fk_name for f in sub_table.foreign_keys):
                        new_fk = PostgresForeignKey(
                            name=fk_name,
                            column_name="id",
                            foreign_table_name=tgt_tbl,
                            foreign_column_name="id",
                            on_delete="CASCADE",
                            relation_id=rel_id,
                        )
                        tables_map[src_tbl] = PostgresTable(
                            name=sub_table.name,
                            class_id=sub_table.class_id,
                            class_name=sub_table.class_name,
                            columns=sub_table.columns,
                            primary_keys=sub_table.primary_keys,
                            foreign_keys=[*sub_table.foreign_keys, new_fk],
                            indices=sub_table.indices,
                        )
                        if tgt_tbl != src_tbl:
                            dependencies[src_tbl].add(tgt_tbl)

            elif rel_type in ("ASSOCIATION", "AGGREGATION", "COMPOSITION"):
                on_del = "CASCADE"
                tgt_card = str(_get_val(rel, "target_cardinality", ""))
                src_card = str(_get_val(rel, "source_cardinality", ""))

                # Si es N:M (Muchos a Muchos) directo sin clase puente
                is_many_to_many = (
                    ("*" in src_card or "n" in src_card.lower() or "m" in src_card.lower())
                    and ("*" in tgt_card or "n" in tgt_card.lower() or "m" in tgt_card.lower())
                )
                if is_many_to_many:
                    j_name = f"{src_tbl}_{tgt_tbl}"
                    if j_name not in tables_map and not any(t.name == j_name for t in junction_tables):
                        j_col1 = f"{src_tbl}_id"
                        j_col2 = f"{tgt_tbl}_id"
                        j_table = PostgresTable(
                            name=j_name,
                            class_id=None,
                            class_name=f"{src_tbl.capitalize()}{tgt_tbl.capitalize()}",
                            columns=[
                                PostgresColumn(name=j_col1, data_type="UUID", is_primary_key=True, is_nullable=False),
                                PostgresColumn(name=j_col2, data_type="UUID", is_primary_key=True, is_nullable=False),
                            ],
                            primary_keys=[j_col1, j_col2],
                            foreign_keys=[
                                PostgresForeignKey(
                                    name=f"fk_{j_name}_{src_tbl}",
                                    column_name=j_col1,
                                    foreign_table_name=src_tbl,
                                    foreign_column_name="id",
                                    on_delete="CASCADE",
                                    relation_id=rel_id,
                                ),
                                PostgresForeignKey(
                                    name=f"fk_{j_name}_{tgt_tbl}",
                                    column_name=j_col2,
                                    foreign_table_name=tgt_tbl,
                                    foreign_column_name="id",
                                    on_delete="CASCADE",
                                    relation_id=rel_id,
                                ),
                            ],
                            indices=[f"idx_{j_name}_{j_col1}", f"idx_{j_name}_{j_col2}"],
                        )
                        junction_tables.append(j_table)
                        dependencies[j_name] = {src_tbl, tgt_tbl}
                else:
                    # 1:N o N:1: La FK va en la tabla hija
                    # Si target_card es "1", la FK vive en src_tbl; si source_card es "1", vive en tgt_tbl
                    dependent_tbl = src_tbl
                    parent_tbl = tgt_tbl
                    if tgt_card in ("1", "0..1") and src_card not in ("1", "0..1"):
                        dependent_tbl = src_tbl
                        parent_tbl = tgt_tbl
                    elif src_card in ("1", "0..1") and tgt_card not in ("1", "0..1"):
                        dependent_tbl = tgt_tbl
                        parent_tbl = src_tbl

                    dep_table = tables_map.get(dependent_tbl)
                    if dep_table:
                        fk_col = f"{parent_tbl}_id"
                        if not any(c.name == fk_col for c in dep_table.columns):
                            # Añadir columna y FK si no estaba ya
                            new_col = PostgresColumn(
                                name=fk_col,
                                data_type="UUID",
                                is_primary_key=False,
                                is_nullable=True,
                            )
                            new_fk = PostgresForeignKey(
                                name=f"fk_{dependent_tbl}_{fk_col}",
                                column_name=fk_col,
                                foreign_table_name=parent_tbl,
                                foreign_column_name="id",
                                on_delete=on_del,
                                relation_id=rel_id,
                            )
                            tables_map[dependent_tbl] = PostgresTable(
                                name=dep_table.name,
                                class_id=dep_table.class_id,
                                class_name=dep_table.class_name,
                                columns=[*dep_table.columns, new_col],
                                primary_keys=dep_table.primary_keys,
                                foreign_keys=[*dep_table.foreign_keys, new_fk],
                                indices=[*dep_table.indices, f"idx_{dependent_tbl}_{fk_col}"],
                            )
                            if parent_tbl != dependent_tbl:
                                dependencies[dependent_tbl].add(parent_tbl)

        all_tables_dict: dict[str, PostgresTable] = dict(tables_map)
        for jt in junction_tables:
            all_tables_dict[jt.name] = jt

        # 3. Ordenamiento Topológico (Kahn) para CREATE TABLE seguro
        sorted_table_names: list[str] = []
        visited: set[str] = set()

        while len(visited) < len(all_tables_dict):
            ready = [
                tbl for tbl in all_tables_dict
                if tbl not in visited and dependencies.get(tbl, set()).issubset(visited)
            ]
            if not ready:
                remaining = [tbl for tbl in all_tables_dict if tbl not in visited]
                remaining.sort()
                sorted_table_names.extend(remaining)
                break

            ready.sort()
            for tbl in ready:
                visited.add(tbl)
                sorted_table_names.append(tbl)

        sorted_tables = [all_tables_dict[name] for name in sorted_table_names]
        return DesiredPostgresSchema(tables=sorted_tables)
