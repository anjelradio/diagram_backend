from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    sanitize_class_attributes,
    to_camel_case,
    to_pascal_case,
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


class DtoGenerator:
    """Generador de clases DTO Request, Response y MessageResponse para Spring Boot."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate_message_response(self) -> GeneratedFile:
        package_path = self.config.package_name.replace(".", "/")
        content = f"""package {self.config.package_name}.dto;

public class MessageResponse {{
    private String message;

    public MessageResponse() {{
    }}

    public MessageResponse(String message) {{
        this.message = message;
    }}

    public String getMessage() {{
        return this.message;
    }}

    public void setMessage(String message) {{
        this.message = message;
    }}
}}
"""
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/dto/MessageResponse.java",
            content=content,
        )

    def generate_request(
        self,
        class_dto: DiagramClassSnapshotDto,
        all_classes: dict[UUID, DiagramClassSnapshotDto] | None = None,
        relations: list[DiagramRelationSnapshotDto] | None = None,
    ) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        dto_name = f"{class_name}Request"

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)
        pk_attr = next((sa for sa in sanitized_attrs if sa.is_primary_key), None)
        req_attrs = [sa for sa in sanitized_attrs if not sa.is_primary_key]

        imports = set()
        for sa in req_attrs:
            if sa.java_import:
                imports.add(sa.java_import)

        # Si el PK es UUID, permitimos ID opcional generado por móvil
        has_uuid_pk = pk_attr is not None and pk_attr.java_type == "UUID"
        if has_uuid_pk:
            imports.add("java.util.UUID")

        # Relaciones ManyToOne legítimas resueltas
        rel_fk_fields: list[dict] = []
        if all_classes:
            deps = resolve_entity_dependencies(class_dto, all_classes, relations)
            for dep in deps:
                # Evitar duplicar si el atributo ya existe en req_attrs
                if not any(sa.field_name == dep.fk_field_name for sa in req_attrs):
                    rel_fk_fields.append({
                        "name": dep.fk_field_name,
                        "type": "UUID",
                        "suffix": dep.fk_method_suffix,
                        "label": dep.label,
                    })
                    imports.add("java.util.UUID")

        code_lines = [
            f"package {self.config.package_name}.dto;",
            "",
        ]
        for imp in sorted(imports):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            f"public class {dto_name} {{",
            "",
        ])

        if has_uuid_pk:
            code_lines.append("    private UUID id;")

        for sa in req_attrs:
            code_lines.append(f"    private {sa.java_type} {sa.field_name};")

        for rf in rel_fk_fields:
            code_lines.append(f"    private {rf["type"]} {rf["name"]};")

        code_lines.extend([
            "",
            f"    public {dto_name}() {{",
            "    }",
            "",
        ])

        if has_uuid_pk:
            code_lines.extend([
                "    public UUID getId() {",
                "        return this.id;",
                "    }",
                "",
                "    public void setId(UUID id) {",
                "        this.id = id;",
                "    }",
                "",
            ])

        for sa in req_attrs:
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

        for rf in rel_fk_fields:
            code_lines.extend([
                f"    public {rf["type"]} get{rf["suffix"]}() {{",
                f"        return this.{rf["name"]};",
                "    }",
                "",
                f"    public void set{rf["suffix"]}({rf["type"]} {rf["name"]}) {{",
                f"        this.{rf["name"]} = {rf["name"]};",
                "    }",
                "",
            ])

        code_lines.append("}")
        code_lines.append("")

        package_path = self.config.package_name.replace(".", "/")
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/dto/{dto_name}.java",
            content="\n".join(code_lines),
        )

    def generate_response(
        self,
        class_dto: DiagramClassSnapshotDto,
        all_classes: dict[UUID, DiagramClassSnapshotDto] | None = None,
        relations: list[DiagramRelationSnapshotDto] | None = None,
    ) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        dto_name = f"{class_name}Response"

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)

        imports = set()
        for sa in sanitized_attrs:
            if sa.java_import:
                imports.add(sa.java_import)

        rel_fk_fields: list[dict] = []
        if all_classes:
            deps = resolve_entity_dependencies(class_dto, all_classes, relations)
            for dep in deps:
                if not any(sa.field_name == dep.fk_field_name for sa in sanitized_attrs):
                    rel_fk_fields.append({
                        "name": dep.fk_field_name,
                        "type": "UUID",
                        "suffix": dep.fk_method_suffix,
                    })
                    imports.add("java.util.UUID")

        code_lines = [
            f"package {self.config.package_name}.dto;",
            "",
        ]
        for imp in sorted(imports):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            f"public class {dto_name} {{",
            "",
        ])

        for sa in sanitized_attrs:
            code_lines.append(f"    private {sa.java_type} {sa.field_name};")

        for rf in rel_fk_fields:
            code_lines.append(f"    private {rf["type"]} {rf["name"]};")

        code_lines.extend([
            "",
            f"    public {dto_name}() {{",
            "    }",
            "",
        ])

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

        for rf in rel_fk_fields:
            code_lines.extend([
                f"    public {rf["type"]} get{rf["suffix"]}() {{",
                f"        return this.{rf["name"]};",
                "    }",
                "",
                f"    public void set{rf["suffix"]}({rf["type"]} {rf["name"]}) {{",
                f"        this.{rf["name"]} = {rf["name"]};",
                "    }",
                "",
            ])

        code_lines.append("}")
        code_lines.append("")

        package_path = self.config.package_name.replace(".", "/")
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/dto/{dto_name}.java",
            content="\n".join(code_lines),
        )
