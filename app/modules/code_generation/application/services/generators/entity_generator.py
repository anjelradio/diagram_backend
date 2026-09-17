from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    map_data_type,
    to_camel_case,
    to_pascal_case,
    to_snake_case,
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

        fields: list[dict] = []
        has_explicit_pk = False

        for attr in class_dto.attributes:
            field_name = to_camel_case(attr.name)
            col_name = to_snake_case(attr.name)
            java_type, imp = map_data_type(attr.data_type)
            if imp:
                imports.add(imp)

            is_pk = attr.is_primary_key
            if is_pk:
                has_explicit_pk = True

            fields.append({
                "name": field_name,
                "type": java_type,
                "column": col_name,
                "is_pk": is_pk,
                "is_nullable": attr.is_nullable,
            })

        # Si no tiene PK explícita, agregamos id por defecto
        if not has_explicit_pk:
            fields.insert(0, {
                "name": "id",
                "type": "Long",
                "column": "id",
                "is_pk": True,
                "is_nullable": False,
            })

        # Procesar relaciones ManyToOne (cuando esta clase es target de 1:N o source de N:1)
        rel_fields: list[dict] = []
        for rel in relations:
            # 1:N -> Target es Many, Source es One
            if rel.target.class_id == class_dto.id:
                source_class = all_classes.get(rel.source.class_id)
                if source_class:
                    source_name = to_pascal_case(source_class.name)
                    field_name = to_camel_case(source_class.name)
                    col_name = f"{to_snake_case(source_class.name)}_id"
                    rel_fields.append({
                        "name": field_name,
                        "type": source_name,
                        "column": col_name,
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

        # Definir campos
        for f in fields:
            if f["is_pk"]:
                code_lines.append("    @Id")
                if f["type"] in ("Long", "Integer"):
                    code_lines.append("    @GeneratedValue(strategy = GenerationType.IDENTITY)")
                elif f["type"] == "UUID":
                    code_lines.append("    @GeneratedValue(strategy = GenerationType.UUID)")
            else:
                nullable_str = "true" if f["is_nullable"] else "false"
                code_lines.append(f'    @Column(name = "{f["column"]}", nullable = {nullable_str})')
            code_lines.append(f'    private {f["type"]} {f["name"]};')
            code_lines.append("")

        # Campos de relaciones
        for rf in rel_fields:
            code_lines.append("    @ManyToOne(fetch = FetchType.LAZY)")
            code_lines.append(f'    @JoinColumn(name = "{rf["column"]}")')
            code_lines.append(f'    private {rf["type"]} {rf["name"]};')
            code_lines.append("")

        # Constructor vacío requerido por JPA
        code_lines.extend([
            f"    public {class_name}() {{",
            "    }",
            "",
        ])

        # Getters y Setters
        all_fields = fields + rel_fields
        for f in all_fields:
            fname = f["name"]
            ftype = f["type"]
            method_suffix = fname[0].upper() + fname[1:] if len(fname) > 1 else fname.upper()

            # Getter
            code_lines.extend([
                f"    public {ftype} get{method_suffix}() {{",
                f"        return this.{fname};",
                "    }",
                "",
            ])

            # Setter
            code_lines.extend([
                f"    public void set{method_suffix}({ftype} {fname}) {{",
                f"        this.{fname} = {fname};",
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
