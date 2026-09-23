from dataclasses import dataclass
from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    to_snake_case,
)
from app.modules.code_generation.application.services.generators.spring_boot_generator import (
    GeneratedSpringBootArchive,
    SpringBootGenerator,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramSnapshotReader,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)


@dataclass(slots=True)
class GenerateSpringBootProjectCommand:
    project_id: UUID
    user_id: str
    package_name: str | None = None
    artifact_id: str | None = None
    database_name: str | None = None


class GenerateSpringBootProjectUseCase:
    """Caso de uso para generar y empaquetar el backend Spring Boot de un proyecto."""

    def __init__(
        self,
        diagram_reader: DiagramSnapshotReader,
        access_policy: DiagramAccessPolicy,
    ) -> None:
        self.diagram_reader = diagram_reader
        self.access_policy = access_policy

    def execute(
        self, command: GenerateSpringBootProjectCommand
    ) -> GeneratedSpringBootArchive:
        project = self.access_policy.ensure_read_access(
            command.project_id, command.user_id
        )

        classes = self.diagram_reader.get_classes_with_attributes_by_project_id(
            command.project_id
        )
        relations = self.diagram_reader.get_relations_by_project_id(
            command.project_id
        )

        slug = to_snake_case(project.name).replace("_", "-")
        artifact_id = command.artifact_id or f"{slug}-backend"
        clean_slug = to_snake_case(project.name).replace("-", "_").lower()
        clean_slug = "".join(c for c in clean_slug if c.isalnum() or c == "_")
        if not clean_slug or clean_slug[0].isdigit():
            clean_slug = f"project_{clean_slug}"
        package_name = command.package_name or f"app.{clean_slug}"
        database_name = command.database_name or f"{clean_slug}_db"

        config = SpringBootProjectConfig(
            project_name=project.name,
            artifact_id=artifact_id,
            group_id="app",
            package_name=package_name,
            database_name=database_name,
        )

        generator = SpringBootGenerator(config)
        return generator.generate(classes, relations)
