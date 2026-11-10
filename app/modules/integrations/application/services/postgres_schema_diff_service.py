from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.integrations.application.services.postgres_target_schema_builder import (
    DesiredPostgresSchema,
    PostgresColumn,
    PostgresForeignKey,
    PostgresTable,
)


@dataclass(frozen=True)
class CurrentPostgresColumn:
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    default_value: str | None = None


@dataclass(frozen=True)
class CurrentPostgresForeignKey:
    constraint_name: str
    column_name: str
    foreign_table_name: str
    foreign_column_name: str


@dataclass(frozen=True)
class CurrentPostgresTable:
    name: str
    columns: dict[str, CurrentPostgresColumn]
    primary_keys: list[str]
    foreign_keys: dict[str, CurrentPostgresForeignKey] = field(default_factory=dict)


@dataclass(frozen=True)
class CurrentPostgresSchema:
    tables: dict[str, CurrentPostgresTable] = field(default_factory=dict)


@dataclass(frozen=True)
class PostgresMigrationSummary:
    created_tables: list[str] = field(default_factory=list)
    dropped_tables: list[str] = field(default_factory=list)
    added_columns: dict[str, list[str]] = field(default_factory=dict)
    dropped_columns: dict[str, list[str]] = field(default_factory=dict)
    altered_columns: dict[str, list[str]] = field(default_factory=dict)
    added_foreign_keys: list[str] = field(default_factory=list)
    dropped_foreign_keys: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.created_tables
            or self.dropped_tables
            or any(cols for cols in self.added_columns.values())
            or any(cols for cols in self.dropped_columns.values())
            or any(cols for cols in self.altered_columns.values())
            or self.added_foreign_keys
            or self.dropped_foreign_keys
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "created_tables": self.created_tables,
            "dropped_tables": self.dropped_tables,
            "added_columns": self.added_columns,
            "dropped_columns": self.dropped_columns,
            "altered_columns": self.altered_columns,
            "added_foreign_keys": self.added_foreign_keys,
            "dropped_foreign_keys": self.dropped_foreign_keys,
        }


@dataclass(frozen=True)
class PostgresMigrationPlan:
    statements: list[str]
    summary: PostgresMigrationSummary

    @property
    def sql_script(self) -> str:
        if not self.statements:
            return "-- Base de datos en Neon ya sincronizada con el diagrama.\n"
        body = "\n".join(f"  {stmt}" for stmt in self.statements)
        return f"BEGIN;\n{body}\nCOMMIT;\n"


def _clean_type_for_comparison(pg_type: str) -> str:
    cleaned = pg_type.strip().lower()
    if "character varying" in cleaned or "varchar" in cleaned:
        return "varchar"
    if "timestamp" in cleaned:
        return "timestamptz"
    if "int" in cleaned:
        return "integer"
    if "numeric" in cleaned or "decimal" in cleaned:
        return "numeric"
    if "bool" in cleaned:
        return "boolean"
    if "double" in cleaned or "float" in cleaned:
        return "double precision"
    return cleaned


class PostgresSchemaDiffService:
    """Motor determinista de 'Versus' que compara el esquema de Neon contra el diagrama UML.

    Genera sentencias DDL en 5 fases libres de conflictos:
    Fase A: Drop de Foreign Keys obsoletas
    Fase B: Drop de tablas eliminadas
    Fase C: Create de tablas nuevas (orden topológico)
    Fase D: Alter de tablas existentes (Regla: nuevas columnas en tablas existentes son siempre NULL)
    Fase E: Add de nuevas Foreign Keys e Índices
    """

    @classmethod
    def generate_diff(
        cls,
        current_schema: CurrentPostgresSchema,
        desired_schema: DesiredPostgresSchema,
    ) -> PostgresMigrationPlan:
        statements: list[str] = []

        created_tables: list[str] = []
        dropped_tables: list[str] = []
        added_columns: dict[str, list[str]] = {}
        dropped_columns: dict[str, list[str]] = {}
        altered_columns: dict[str, list[str]] = {}
        added_foreign_keys: list[str] = []
        dropped_foreign_keys: list[str] = []

        current_tables = current_schema.tables
        desired_tables = desired_schema.tables_by_name

        # =====================================================================
        # FASE A: Drop de Foreign Keys obsoletas
        # =====================================================================
        for tbl_name, cur_tbl in current_tables.items():
            des_tbl = desired_tables.get(tbl_name)
            for fk_name, cur_fk in cur_tbl.foreign_keys.items():
                should_drop = False
                if des_tbl is None:
                    # La tabla completa será eliminada en la Fase B
                    should_drop = True
                else:
                    # Si la relación o columna referenciada ya no existe en desired
                    desired_fks = des_tbl.foreign_keys
                    matching_fk = next(
                        (
                            dfk for dfk in desired_fks
                            if dfk.column_name == cur_fk.column_name
                            and dfk.foreign_table_name == cur_fk.foreign_table_name
                        ),
                        None,
                    )
                    if matching_fk is None:
                        should_drop = True

                if should_drop:
                    stmt = f'ALTER TABLE "public"."{tbl_name}" DROP CONSTRAINT IF EXISTS "{cur_fk.constraint_name}";'
                    statements.append(stmt)
                    dropped_foreign_keys.append(f"{tbl_name}.{cur_fk.constraint_name}")

        # =====================================================================
        # FASE B: Drop de Tablas eliminadas del diagrama
        # =====================================================================
        for tbl_name in sorted(current_tables.keys()):
            if tbl_name not in desired_tables:
                stmt = f'DROP TABLE IF EXISTS "public"."{tbl_name}" CASCADE;'
                statements.append(stmt)
                dropped_tables.append(tbl_name)

        # =====================================================================
        # FASE C: Creación de Tablas Nuevas (en orden topológico)
        # =====================================================================
        for des_tbl in desired_schema.tables:
            tbl_name = des_tbl.name
            if tbl_name not in current_tables:
                col_defs: list[str] = []
                for col in des_tbl.columns:
                    parts = [f'"{col.name}"', col.data_type]
                    if col.default_value:
                        parts.append(f"DEFAULT {col.default_value}")
                    if not col.is_nullable:
                        parts.append("NOT NULL")
                    col_defs.append(" ".join(parts))

                if des_tbl.primary_keys:
                    pk_cols = ", ".join(f'"{pk}"' for pk in des_tbl.primary_keys)
                    col_defs.append(f'CONSTRAINT "pk_{tbl_name}" PRIMARY KEY ({pk_cols})')

                col_block = ",\n    ".join(col_defs)
                stmt = f'CREATE TABLE IF NOT EXISTS "public"."{tbl_name}" (\n    {col_block}\n);'
                statements.append(stmt)
                created_tables.append(tbl_name)

        # =====================================================================
        # FASE D: Evolución de Tablas Existentes (ALTER TABLE con NULL seguro)
        # =====================================================================
        for des_tbl in desired_schema.tables:
            tbl_name = des_tbl.name
            if tbl_name in current_tables:
                cur_tbl = current_tables[tbl_name]

                # 1. Columnas eliminadas
                cols_to_drop = [
                    col_name for col_name in cur_tbl.columns
                    if col_name not in des_tbl.columns_by_name
                ]
                for col_name in sorted(cols_to_drop):
                    stmt = f'ALTER TABLE "public"."{tbl_name}" DROP COLUMN IF EXISTS "{col_name}";'
                    statements.append(stmt)
                    dropped_columns.setdefault(tbl_name, []).append(col_name)

                # 2. Nuevas columnas agregadas (REGLA: SIEMPRE NULL EN TABLAS EXISTENTES)
                cols_to_add = [
                    col for col in des_tbl.columns
                    if col.name not in cur_tbl.columns
                ]
                for col in cols_to_add:
                    # Regla obligatoria: en ALTER TABLE ADD COLUMN sobre tablas existentes,
                    # se agrega como NULL (anulable) para evitar errores si la tabla tiene datos.
                    stmt = f'ALTER TABLE "public"."{tbl_name}" ADD COLUMN "{col.name}" {col.data_type} NULL;'
                    statements.append(stmt)
                    added_columns.setdefault(tbl_name, []).append(col.name)

                # 3. Cambio de tipo de dato en columna existente
                for col in des_tbl.columns:
                    if col.name in cur_tbl.columns:
                        cur_col = cur_tbl.columns[col.name]
                        if _clean_type_for_comparison(cur_col.data_type) != _clean_type_for_comparison(col.data_type):
                            stmt = (
                                f'ALTER TABLE "public"."{tbl_name}" ALTER COLUMN "{col.name}" '
                                f'TYPE {col.data_type} USING "{col.name}"::{col.data_type};'
                            )
                            statements.append(stmt)
                            altered_columns.setdefault(tbl_name, []).append(f"{col.name} ({cur_col.data_type} -> {col.data_type})")

        # =====================================================================
        # FASE E: Creación de Nuevas Foreign Keys e Índices
        # =====================================================================
        for des_tbl in desired_schema.tables:
            tbl_name = des_tbl.name
            cur_tbl = current_tables.get(tbl_name)

            for fk in des_tbl.foreign_keys:
                # Comprobar si ya existe una FK equivalente en Neon
                has_fk = False
                if cur_tbl is not None:
                    has_fk = any(
                        cfk.column_name == fk.column_name
                        and cfk.foreign_table_name == fk.foreign_table_name
                        for cfk in cur_tbl.foreign_keys.values()
                    )
                if not has_fk:
                    stmt = (
                        f'ALTER TABLE "public"."{tbl_name}" ADD CONSTRAINT "{fk.name}" '
                        f'FOREIGN KEY ("{fk.column_name}") REFERENCES "public"."{fk.foreign_table_name}" ("{fk.foreign_column_name}") '
                        f'ON UPDATE {fk.on_update} ON DELETE {fk.on_delete};'
                    )
                    statements.append(stmt)
                    added_foreign_keys.append(f"{tbl_name}.{fk.name}")

            for idx in des_tbl.indices:
                # Extraer columna del nombre del índice: idx_tabla_columna
                col_part = idx.replace(f"idx_{tbl_name}_", "")
                if col_part in des_tbl.columns_by_name:
                    stmt = f'CREATE INDEX IF NOT EXISTS "{idx}" ON "public"."{tbl_name}" ("{col_part}");'
                    statements.append(stmt)

        summary = PostgresMigrationSummary(
            created_tables=created_tables,
            dropped_tables=dropped_tables,
            added_columns=added_columns,
            dropped_columns=dropped_columns,
            altered_columns=altered_columns,
            added_foreign_keys=added_foreign_keys,
            dropped_foreign_keys=dropped_foreign_keys,
        )
        return PostgresMigrationPlan(statements=statements, summary=summary)
