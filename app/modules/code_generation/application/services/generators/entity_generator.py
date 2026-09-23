from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    sanitize_class_attributes,
    to_camel_case,
    to_pascal_case,
    to_snake_case,
)
from app.modules.code_generation.application.services.generators.relation_resolver import (
    resolve_entity_dependencies,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


class EntityGenerator:
    """Generador de clases Java @Entity anotadas con JPA."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(
        self,
        class_dto: DiagramClassSnapshotDto,
        all_classes: dict[UUID, DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto],
    ) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        table_name = to_snake_case(class_dto.name)

        imports = {
            "jakarta.persistence.*",
        }

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)
        for sa in sanitized_attrs:
            if sa.java_import:
                imports.add(sa.java_import)

        # Procesar relaciones ManyToOne legítimas resueltas
        rel_fields: list[dict] = []
        if all_classes:
            deps = resolve_entity_dependencies(class_dto, all_classes, relations)
            for dep in deps:
                rel_fields.append({
                    "name": dep.field_name,
                    "type": dep.referenced_class_name,
                    "column": dep.fk_column_name,
                    "rel_type": "ManyToOne",
                })

        code_lines = [
            f"package {self.config.package_name}.model;",
            "",
        ]

        # Agregar imports ordenados
        for imp in sorted(imports):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            "@Entity",
            f'@Table(name = "{table_name}")',
            f"public class {class_name} {{",
            "",
        ])

        existing_cols = {sa.column_name for sa in sanitized_attrs}

        # Definir campos
        for sa in sanitized_attrs:
            if sa.is_primary_key:
                code_lines.append("    @Id")
                if sa.java_type in ("Long", "Integer"):
                    code_lines.append("    @GeneratedValue(strategy = GenerationType.IDENTITY)")
                code_lines.append(f'    @Column(name = "{sa.column_name}", nullable = false, updatable = false)')
            else:
                nullable_str = "true" if sa.is_nullable else "false"
                code_lines.append(f'    @Column(name = "{sa.column_name}", nullable = {nullable_str})')
            code_lines.append(f'    private {sa.java_type} {sa.field_name};')
            code_lines.append("")

        # Campos de relaciones
        for rf in rel_fields:
            code_lines.append("    @ManyToOne(fetch = FetchType.LAZY)")
            if rf["column"] in existing_cols:
                code_lines.append(f'    @JoinColumn(name = "{rf["column"]}", insertable = false, updatable = false)')
            else:
                code_lines.append(f'    @JoinColumn(name = "{rf["column"]}")')
            code_lines.append(f'    private {rf["type"]} {rf["name"]};')
            code_lines.append("")

        # Constructor vacío requerido por JPA
        code_lines.extend([
            f"    public {class_name}() {{",
            "    }",
            "",
        ])

        # Getters y Setters para atributos sanitizados
        for sa in sanitized_attrs:
            code_lines.extend([
                f"    public {sa.java_type} get{sa.method_suffix}() {{",
                f"        return this.{sa.field_name};",
                "    }",
                "",
                f"    public void set{sa.method_suffix}({sa.java_type} {sa.field_name}) {{",
                f"        this.{sa.field_name} = {sa.field_name};",
                "    }",
                "",
            ])

        # Getters y Setters para relaciones
        for rf in rel_fields:
            rf_suffix = rf["name"][0].upper() + rf["name"][1:] if len(rf["name"]) > 1 else rf["name"].upper()
            code_lines.extend([
                f"    public {rf['type']} get{rf_suffix}() {{",
                f"        return this.{rf['name']};",
                "    }",
                "",
                f"    public void set{rf_suffix}({rf['type']} {rf['name']}) {{",
                f"        this.{rf['name']} = {rf['name']};",
                "    }",
                "",
            ])

        code_lines.append("}")
        code_lines.append("")

        package_path = self.config.package_name.replace(".", "/")
        relative_path = f"src/main/java/{package_path}/model/{class_name}.java"

        return GeneratedFile(
            relative_path=relative_path,
            content="\n".join(code_lines),
        )
