from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    sanitize_class_attributes,
    to_kebab_case,
    to_pascal_case,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
)


class ControllerGenerator:
    """Generador de controladores REST (@RestController) de Spring Boot con respuestas uniformes."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(self, class_dto: DiagramClassSnapshotDto) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        controller_name = f"{class_name}Controller"
        service_name = f"{class_name}Service"
        service_var = f"{class_name[0].lower()}{class_name[1:]}Service"
        req_dto = f"{class_name}Request"
        res_dto = f"{class_name}Response"
        endpoint_path = to_kebab_case(class_dto.name)

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)
        pk_attr = next(sa for sa in sanitized_attrs if sa.is_primary_key)
        pk_type = pk_attr.java_type
        pk_import = pk_attr.java_import

        imports = [
            "java.util.List",
            "jakarta.validation.Valid",
            "org.springframework.http.HttpStatus",
            "org.springframework.web.bind.annotation.*",
            f"{self.config.package_name}.dto.{req_dto}",
            f"{self.config.package_name}.dto.{res_dto}",
            f"{self.config.package_name}.dto.MessageResponse",
            f"{self.config.package_name}.service.{service_name}",
        ]
        if pk_import:
            imports.append(pk_import)

        code_lines = [
            f"package {self.config.package_name}.controller;",
            "",
        ]
        for imp in sorted(set(imports)):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            "@RestController",
            f"@RequestMapping(\"/api/{endpoint_path}\")",
            f"public class {controller_name} {{",
            "",
            f"    private final {service_name} {service_var};",
            "",
            f"    public {controller_name}({service_name} {service_var}) {{",
            f"        this.{service_var} = {service_var};",
            "    }",
            "",
            "    @GetMapping",
            f"    public List<{res_dto}> getAll() {{",
            f"        return {service_var}.findAll();",
            "    }",
            "",
            "    @GetMapping(\"/{id}\")",
            f"    public {res_dto} getById(@PathVariable(\"id\") {pk_type} id) {{",
            f"        return {service_var}.findById(id);",
            "    }",
            "",
            "    @PostMapping",
            "    @ResponseStatus(HttpStatus.CREATED)",
            f"    public MessageResponse create(@Valid @RequestBody {req_dto} request) {{",
            f"        {service_var}.create(request);",
            f"        return new MessageResponse(\"{class_name} registrado correctamente\");",
            "    }",
            "",
            "    @PutMapping(\"/{id}\")",
            f"    public MessageResponse update(@PathVariable(\"id\") {pk_type} id, @Valid @RequestBody {req_dto} request) {{",
            f"        {service_var}.update(id, request);",
            f"        return new MessageResponse(\"{class_name} actualizado correctamente\");",
            "    }",
            "",
            "    @DeleteMapping(\"/{id}\")",
            f"    public MessageResponse delete(@PathVariable(\"id\") {pk_type} id) {{",
            f"        {service_var}.deleteById(id);",
            f"        return new MessageResponse(\"{class_name} eliminado correctamente\");",
            "    }",
            "}",
            "",
        ])

        package_path = self.config.package_name.replace(".", "/")
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/controller/{controller_name}.java",
            content="\n".join(code_lines),
        )
