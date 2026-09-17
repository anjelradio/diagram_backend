from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    map_data_type,
    to_camel_case,
    to_pascal_case,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
)


class DtoGenerator:
    """Generador de clases DTO Request y Response para Spring Boot."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate_request(self, class_dto: DiagramClassSnapshotDto) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        dto_name = f"{class_name}Request"

        imports = set()
        fields = []

        for attr in class_dto.attributes:
            if attr.is_primary_key:
                continue  # Request no necesita el ID generado
            field_name = to_camel_case(attr.name)
            java_type, imp = map_data_type(attr.data_type)
            if imp:
                imports.add(imp)
            fields.append({"name": field_name, "type": java_type})

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

        for f in fields:
            code_lines.append(f'    private {f["type"]} {f["name"]};')
        code_lines.append("")

        code_lines.extend([
            f"    public {dto_name}() {{",
            "    }",
            "",
        ])

        for f in fields:
            fname = f["name"]
            ftype = f["type"]
            method_suffix = fname[0].upper() + fname[1:] if len(fname) > 1 else fname.upper()

            code_lines.extend([
                f"    public {ftype} get{method_suffix}() {{",
                f"        return this.{fname};",
                "    }",
                "",
                f"    public void set{method_suffix}({ftype} {fname}) {{",
                f"        this.{fname} = {fname};",
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

    def generate_response(self, class_dto: DiagramClassSnapshotDto) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        dto_name = f"{class_name}Response"

        imports = set()
        fields = []
        has_pk = False

        for attr in class_dto.attributes:
            field_name = to_camel_case(attr.name)
            java_type, imp = map_data_type(attr.data_type)
            if imp:
                imports.add(imp)
            if attr.is_primary_key:
                has_pk = True
            fields.append({"name": field_name, "type": java_type})

        if not has_pk:
            fields.insert(0, {"name": "id", "type": "Long"})

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

        for f in fields:
            code_lines.append(f'    private {f["type"]} {f["name"]};')
        code_lines.append("")

        code_lines.extend([
            f"    public {dto_name}() {{",
            "    }",
            "",
        ])

        for f in fields:
            fname = f["name"]
            ftype = f["type"]
            method_suffix = fname[0].upper() + fname[1:] if len(fname) > 1 else fname.upper()

            code_lines.extend([
                f"    public {ftype} get{method_suffix}() {{",
                f"        return this.{fname};",
                "    }",
                "",
                f"    public void set{method_suffix}({ftype} {fname}) {{",
                f"        this.{fname} = {fname};",
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
