from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    sanitize_class_attributes,
    to_pascal_case,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
)


class RepositoryGenerator:
    """Generador de interfaces Spring Data JPA Repository."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(self, class_dto: DiagramClassSnapshotDto) -> GeneratedFile:
        class_name = to_pascal_case(class_dto.name)
        repo_name = f"{class_name}Repository"

        sanitized_attrs = sanitize_class_attributes(class_dto.attributes)
        pk_attr = next(sa for sa in sanitized_attrs if sa.is_primary_key)
        pk_type = pk_attr.java_type
        pk_import = pk_attr.java_import

        imports = [
            "org.springframework.data.jpa.repository.JpaRepository",
            "org.springframework.stereotype.Repository",
            f"{self.config.package_name}.model.{class_name}",
        ]
        if pk_import:
            imports.append(pk_import)

        code_lines = [
            f"package {self.config.package_name}.repository;",
            "",
        ]
        for imp in sorted(set(imports)):
            code_lines.append(f"import {imp};")

        code_lines.extend([
            "",
            "@Repository",
            f"public interface {repo_name} extends JpaRepository<{class_name}, {pk_type}> {{",
            "}",
            "",
        ])

        package_path = self.config.package_name.replace(".", "/")
        relative_path = f"src/main/java/{package_path}/repository/{repo_name}.java"

        return GeneratedFile(
            relative_path=relative_path,
            content="\n".join(code_lines),
        )
