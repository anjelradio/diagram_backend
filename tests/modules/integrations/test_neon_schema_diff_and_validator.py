import pytest
from uuid import uuid4

from app.modules.integrations.application.services.postgres_diagram_validator import (
    PostgresDiagramValidator,
)
from app.modules.integrations.application.services.postgres_target_schema_builder import (
    PostgresTargetSchemaBuilder,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresColumn,
    CurrentPostgresForeignKey,
    CurrentPostgresSchema,
    CurrentPostgresTable,
    PostgresSchemaDiffService,
)
from app.modules.integrations.domain.exceptions import (
    NeonDiagramValidationException,
)


def test_validator_rejects_empty_diagram():
    with pytest.raises(NeonDiagramValidationException) as exc_info:
        PostgresDiagramValidator.validate([])
    assert "El diagrama está vacío" in str(exc_info.value)


def test_validator_rejects_duplicate_class_names_and_tables():
    c1_id = uuid4()
    c2_id = uuid4()
    classes = [
        {"id": c1_id, "name": "Producto", "attributes": []},
        {"id": c2_id, "name": "producto", "attributes": []},
    ]
    with pytest.raises(NeonDiagramValidationException) as exc_info:
        PostgresDiagramValidator.validate(classes)
    assert "Conflicto" in str(exc_info.value)


def test_validator_rejects_duplicate_attributes_in_class():
    c_id = uuid4()
    classes = [
        {
            "id": c_id,
            "name": "Cliente",
            "attributes": [
                {"id": uuid4(), "name": "email", "data_type": "TEXT"},
                {"id": uuid4(), "name": "Email", "data_type": "TEXT"},
            ],
        }
    ]
    with pytest.raises(NeonDiagramValidationException) as exc_info:
        PostgresDiagramValidator.validate(classes)
    assert "está duplicado" in str(exc_info.value)


def test_target_schema_builder_topological_sort_and_types():
    cat_id = uuid4()
    prod_id = uuid4()

    classes = [
        {
            "id": prod_id,
            "name": "Producto",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "nombre", "data_type": "TEXT", "is_nullable": False},
                {"id": uuid4(), "name": "precio", "data_type": "DECIMAL", "is_nullable": False},
                {"id": uuid4(), "name": "categoria_id", "data_type": "UUID", "is_foreign_key": True, "referenced_class_id": cat_id, "is_nullable": True},
            ],
        },
        {
            "id": cat_id,
            "name": "Categoria",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "descripcion", "data_type": "TEXT", "is_nullable": True},
            ],
        },
    ]

    schema = PostgresTargetSchemaBuilder.build(classes)
    table_names = [t.name for t in schema.tables]
    # Categoria (sin dependencias) debe crearse antes que Producto (que depende de Categoria)
    assert table_names.index("categoria") < table_names.index("producto")

    prod_table = schema.tables_by_name["producto"]
    assert prod_table.columns_by_name["nombre"].data_type == "TEXT"
    assert prod_table.columns_by_name["precio"].data_type == "NUMERIC(12, 2)"
    assert len(prod_table.foreign_keys) == 1
    assert prod_table.foreign_keys[0].foreign_table_name == "categoria"
    assert prod_table.foreign_keys[0].on_delete == "CASCADE"


def test_schema_diff_initial_deployment():
    c_id = uuid4()
    classes = [
        {
            "id": c_id,
            "name": "Usuario",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "email", "data_type": "TEXT", "is_nullable": False},
            ],
        }
    ]
    desired = PostgresTargetSchemaBuilder.build(classes)
    current = CurrentPostgresSchema(tables={})

    plan = PostgresSchemaDiffService.generate_diff(current, desired)
    assert len(plan.statements) == 1
    assert "CREATE TABLE IF NOT EXISTS \"public\".\"usuario\"" in plan.statements[0]
    assert plan.summary.created_tables == ["usuario"]
    assert "BEGIN;" in plan.sql_script
    assert "COMMIT;" in plan.sql_script


def test_schema_diff_applies_safe_nullable_rule_on_existing_table():
    c_id = uuid4()
    classes = [
        {
            "id": c_id,
            "name": "Usuario",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "email", "data_type": "TEXT", "is_nullable": False},
                # Nuevo atributo marcado NOT NULL en el diagrama
                {"id": uuid4(), "name": "telefono", "data_type": "TEXT", "is_nullable": False},
            ],
        }
    ]
    desired = PostgresTargetSchemaBuilder.build(classes)

    # En Neon ya existía la tabla 'usuario' con sólo 'id' y 'email'
    current = CurrentPostgresSchema(
        tables={
            "usuario": CurrentPostgresTable(
                name="usuario",
                columns={
                    "id": CurrentPostgresColumn(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
                    "email": CurrentPostgresColumn(name="email", data_type="text", is_nullable=False, is_primary_key=False),
                },
                primary_keys=["id"],
            )
        }
    )

    plan = PostgresSchemaDiffService.generate_diff(current, desired)
    # Debe generar ALTER TABLE ADD COLUMN "telefono" TEXT NULL
    add_stmt = next((s for s in plan.statements if "ADD COLUMN" in s), None)
    assert add_stmt is not None
    assert 'ALTER TABLE "public"."usuario" ADD COLUMN "telefono" TEXT NULL;' in add_stmt
    assert plan.summary.added_columns["usuario"] == ["telefono"]


def test_schema_diff_drops_foreign_key_before_dropping_deleted_table():
    cat_id = uuid4()
    prod_id = uuid4()

    # Diagrama deseado: sólo queda Producto (se borró Categoria y su FK)
    classes = [
        {
            "id": prod_id,
            "name": "Producto",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "nombre", "data_type": "TEXT", "is_nullable": False},
            ],
        }
    ]
    desired = PostgresTargetSchemaBuilder.build(classes)

    # Esquema actual en Neon: existen ambas tablas y la FK
    current = CurrentPostgresSchema(
        tables={
            "categoria": CurrentPostgresTable(
                name="categoria",
                columns={"id": CurrentPostgresColumn(name="id", data_type="uuid", is_nullable=False, is_primary_key=True)},
                primary_keys=["id"],
            ),
            "producto": CurrentPostgresTable(
                name="producto",
                columns={
                    "id": CurrentPostgresColumn(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
                    "nombre": CurrentPostgresColumn(name="nombre", data_type="text", is_nullable=False, is_primary_key=False),
                    "categoria_id": CurrentPostgresColumn(name="categoria_id", data_type="uuid", is_nullable=True, is_primary_key=False),
                },
                primary_keys=["id"],
                foreign_keys={
                    "fk_producto_categoria": CurrentPostgresForeignKey(
                        constraint_name="fk_producto_categoria",
                        column_name="categoria_id",
                        foreign_table_name="categoria",
                        foreign_column_name="id",
                    )
                },
            ),
        }
    )

    plan = PostgresSchemaDiffService.generate_diff(current, desired)
    # Orden garantizado: 1º DROP CONSTRAINT fk_producto_categoria, 2º DROP TABLE categoria, 3º DROP COLUMN categoria_id
    fk_drop_idx = next(i for i, s in enumerate(plan.statements) if "DROP CONSTRAINT IF EXISTS \"fk_producto_categoria\"" in s)
    tbl_drop_idx = next(i for i, s in enumerate(plan.statements) if "DROP TABLE IF EXISTS \"public\".\"categoria\"" in s)
    col_drop_idx = next(i for i, s in enumerate(plan.statements) if "DROP COLUMN IF EXISTS \"categoria_id\"" in s)

    assert fk_drop_idx < tbl_drop_idx
    assert tbl_drop_idx < col_drop_idx
    assert plan.summary.dropped_tables == ["categoria"]
    assert "categoria_id" in plan.summary.dropped_columns["producto"]


def test_schema_diff_creates_foreign_keys_with_on_delete_cascade():
    cat_id = uuid4()
    prod_id = uuid4()

    classes = [
        {
            "id": cat_id,
            "name": "Categoria",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
            ],
        },
        {
            "id": prod_id,
            "name": "Producto",
            "attributes": [
                {"id": uuid4(), "name": "id", "data_type": "UUID", "is_primary_key": True, "is_nullable": False},
                {"id": uuid4(), "name": "categoria_id", "data_type": "UUID", "is_foreign_key": True, "referenced_class_id": cat_id, "is_nullable": True},
            ],
        },
    ]
    desired = PostgresTargetSchemaBuilder.build(classes)
    current = CurrentPostgresSchema(tables={})

    plan = PostgresSchemaDiffService.generate_diff(current, desired)
    fk_stmt = next((s for s in plan.statements if "ADD CONSTRAINT" in s and "FOREIGN KEY" in s), None)
    assert fk_stmt is not None
    assert "ON UPDATE CASCADE ON DELETE CASCADE" in fk_stmt
