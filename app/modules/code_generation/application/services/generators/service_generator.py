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


class ServiceGenerator:
    """Generador de clases @Service de Spring Boot con operaciones CRUD y validacion conversacional."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(
        self,
        class_dto: DiagramClassSnapshotDto,
        all_classes: dict[UUID, DiagramClassSnapshotDto] | None = None,
        relations: list[DiagramRelationSnapshotDto] | None = None,
    ) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        service_name = f"{class_name}Service"
        repo_name = f"{class_name}Repository"
        repo_var = f"{class_name[0].lower()}{class_name[1:]}Repository"
        req_dto = f"{class_name}Request"
        res_dto = f"{class_name}Response"

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)
        pk_attr = next(sa for sa in sanitized_attrs if sa.is_primary_key)
        pk_type = pk_attr.java_type
        pk_import = pk_attr.java_import

        imports = [
            "java.util.List",
            "java.util.stream.Collectors",
            "org.springframework.stereotype.Service",
            "org.springframework.transaction.annotation.Transactional",
            "org.springframework.web.server.ResponseStatusException",
            "org.springframework.http.HttpStatus",
            f"{self.config.package_name}.model.{class_name}",
            f"{self.config.package_name}.repository.{repo_name}",
            f"{self.config.package_name}.dto.{req_dto}",
            f"{self.config.package_name}.dto.{res_dto}",
        ]
        if pk_import:
            imports.append(pk_import)
        if pk_type == "UUID":
            imports.append("java.util.UUID")

        # Detectar relaciones ManyToOne legítimas donde esta entidad depende de otra
        rel_deps: list[dict] = []
        if all_classes:
            deps = resolve_entity_dependencies(class_dto, all_classes, relations)
            for dep in deps:
                rel_deps.append({
                    "class_name": dep.referenced_class_name,
                    "repo_name": dep.repo_name,
                    "repo_var": dep.repo_var,
                    "field_name": dep.field_name,
                    "getter_id": f"get{dep.fk_method_suffix}",
                    "setter_entity": f"set{dep.method_suffix}",
                    "label": dep.label,
                    "is_nullable": dep.is_nullable,
                })
                imports.append(f"{self.config.package_name}.model.{dep.referenced_class_name}")
                imports.append(f"{self.config.package_name}.repository.{dep.repo_name}")

        code_lines = [
            f"package {self.config.package_name}.service;",
            "",
        ]
        for imp in sorted(set(imports)):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            "@Service",
            "@Transactional",
            f"public class {service_name} {{",
            "",
            f"    private final {repo_name} {repo_var};",
        ])

        for rd in rel_deps:
            code_lines.append(f"    private final {rd['repo_name']} {rd['repo_var']};")

        # Constructor con inyeccion de dependencias
        ctor_params = [f"{repo_name} {repo_var}"]
        for rd in rel_deps:
            ctor_params.append(f"{rd['repo_name']} {rd['repo_var']}")
        code_lines.extend([
            "",
            f"    public {service_name}({', '.join(ctor_params)}) {{",
            f"        this.{repo_var} = {repo_var};",
        ])
        for rd in rel_deps:
            code_lines.append(f"        this.{rd['repo_var']} = {rd['repo_var']};")
        code_lines.extend([
            "    }",
            "",
            "    @Transactional(readOnly = true)",
            f"    public List<{res_dto}> findAll() {{",
            f"        return {repo_var}.findAll().stream()",
            "            .map(this::toResponse)",
            "            .collect(Collectors.toList());",
            "    }",
            "",
            "    @Transactional(readOnly = true)",
            f"    public {res_dto} findById({pk_type} id) {{",
            f"        {class_name} entity = {repo_var}.findById(id)",
            f'            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "{class_name} no encontrado"));',
            "        return toResponse(entity);",
            "    }",
            "",
            f"    public {res_dto} create({req_dto} request) {{",
            f"        {class_name} entity = toEntity(request);",
            f"        {class_name} saved = {repo_var}.save(entity);",
            "        return toResponse(saved);",
            "    }",
            "",
            f"    public {res_dto} update({pk_type} id, {req_dto} request) {{",
            f"        {class_name} entity = {repo_var}.findById(id)",
            f'            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "{class_name} no encontrado"));',
            "        updateEntity(entity, request);",
            f"        {class_name} updated = {repo_var}.save(entity);",
            "        return toResponse(updated);",
            "    }",
            "",
            f"    public void deleteById({pk_type} id) {{",
            f"        if (!{repo_var}.existsById(id)) {{",
            f'            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "{class_name} no encontrado");',
            "        }",
            f"        {repo_var}.deleteById(id);",
            "    }",
            "",
            f"    private {res_dto} toResponse({class_name} entity) {{",
            f"        {res_dto} response = new {res_dto}();",
        ])

        for sa in sanitized_attrs:
            code_lines.append(f"        response.set{sa.method_suffix}(entity.get{sa.method_suffix}());")

        for rd in rel_deps:
            code_lines.extend([
                f"        if (entity.get{rd['class_name']}() != null) {{",
                f"            response.set{rd['class_name']}Id(entity.get{rd['class_name']}().getId());",
                "        }",
            ])

        code_lines.extend([
            "        return response;",
            "    }",
            "",
            f"    private {class_name} toEntity({req_dto} request) {{",
            f"        {class_name} entity = new {class_name}();",
        ])

        if pk_type == "UUID":
            code_lines.extend([
                "        if (request.getId() != null) {",
                "            entity.setId(request.getId());",
                "        } else {",
                "            entity.setId(UUID.randomUUID());",
                "        }",
            ])

        for sa in sanitized_attrs:
            if sa.is_primary_key:
                continue
            code_lines.append(f"        entity.set{sa.method_suffix}(request.get{sa.method_suffix}());")

        for rd in rel_deps:
            if not rd["is_nullable"]:
                code_lines.extend([
                    f"        if (request.{rd['getter_id']}() == null) {{",
                    f'            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "{rd["label"]} obligatoria");',
                    "        }",
                    f"        {rd['class_name']} {rd['field_name']} = this.{rd['repo_var']}.findById(request.{rd['getter_id']}())",
                    f'            .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "{rd["label"]} no encontrada"));',
                    f"        entity.{rd['setter_entity']}({rd['field_name']});",
                ])
            else:
                code_lines.extend([
                    f"        if (request.{rd['getter_id']}() != null) {{",
                    f"            {rd['class_name']} {rd['field_name']} = this.{rd['repo_var']}.findById(request.{rd['getter_id']}())",
                    f'                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "{rd["label"]} no encontrada"));',
                    f"            entity.{rd['setter_entity']}({rd['field_name']});",
                    "        }",
                ])

        code_lines.extend([
            "        return entity;",
            "    }",
            "",
            f"    private void updateEntity({class_name} entity, {req_dto} request) {{",
        ])

        for sa in sanitized_attrs:
            if sa.is_primary_key:
                continue
            code_lines.append(f"        entity.set{sa.method_suffix}(request.get{sa.method_suffix}());")

        for rd in rel_deps:
            code_lines.extend([
                f"        if (request.{rd['getter_id']}() != null) {{",
                f"            {rd['class_name']} {rd['field_name']} = this.{rd['repo_var']}.findById(request.{rd['getter_id']}())",
                f'                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "{rd["label"]} no encontrada"));',
                f"            entity.{rd['setter_entity']}({rd['field_name']});",
                "        }",
            ])

        code_lines.extend([
            "    }",
            "}",
            "",
        ])

        package_path = self.config.package_name.replace(".", "/")
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/service/{service_name}.java",
            content="\n".join(code_lines),
        )
