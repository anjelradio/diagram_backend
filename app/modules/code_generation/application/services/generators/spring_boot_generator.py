import io
import zipfile
from dataclasses import dataclass
from uuid import UUID

from app.modules.code_generation.application.services.generators.capabilities_generator import (
    CapabilitiesGenerator,
)
from app.modules.code_generation.application.services.generators.controller_generator import (
    ControllerGenerator,
)
from app.modules.code_generation.application.services.generators.docker_generator import (
    DockerAndConfigGenerator,
)
from app.modules.code_generation.application.services.generators.dto_generator import (
    DtoGenerator,
)
from app.modules.code_generation.application.services.generators.entity_generator import (
    EntityGenerator,
)
from app.modules.code_generation.application.services.generators.exception_handler_generator import (
    ExceptionHandlerGenerator,
)
from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    to_snake_case,
)
from app.modules.code_generation.application.services.generators.repository_generator import (
    RepositoryGenerator,
)
from app.modules.code_generation.application.services.generators.service_generator import (
    ServiceGenerator,
)
from app.modules.code_generation.application.services.generators.sqlite_schema_generator import (
    SqliteSchemaGenerator,
)
from app.modules.code_generation.domain.exceptions import EmptyDiagramException
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


@dataclass(frozen=True, slots=True)
class GeneratedSpringBootArchive:
    """Resultado final del empaquetado ZIP del backend Spring Boot."""

    filename: str
    zip_bytes: bytes
    total_files: int


class SpringBootGenerator:
    """Coordinador maestro de generación de proyectos Spring Boot."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config
        self.entity_gen = EntityGenerator(config)
        self.repo_gen = RepositoryGenerator(config)
        self.dto_gen = DtoGenerator(config)
        self.service_gen = ServiceGenerator(config)
        self.controller_gen = ControllerGenerator(config)
        self.docker_gen = DockerAndConfigGenerator(config)
        self.exception_handler_gen = ExceptionHandlerGenerator(config)
        self.capabilities_gen = CapabilitiesGenerator(config)
        self.sqlite_schema_gen = SqliteSchemaGenerator(config)

    def generate(
        self,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto],
    ) -> GeneratedSpringBootArchive:
        if not classes:
            raise EmptyDiagramException()

        all_classes_map: dict[UUID, DiagramClassSnapshotDto] = {
            c.id: c for c in classes
        }

        files: list[GeneratedFile] = []

        # 1. Generar archivos base y Docker
        files.extend(self.docker_gen.generate_all(classes, relations))

        # 2. Generar capacidades para IA local, esquema SQLite DDL, DTOs compartidos y manejador global de excepciones
        files.append(self.capabilities_gen.generate(classes, relations))
        files.append(self.sqlite_schema_gen.generate(classes, relations))
        files.append(self.dto_gen.generate_message_response())
        files.append(self.exception_handler_gen.generate())

        # 3. Generar capas para cada clase
        for class_dto in classes:
            # Model
            files.append(self.entity_gen.generate(class_dto, all_classes_map, relations))
            # Repository
            files.append(self.repo_gen.generate(class_dto))
            # DTOs
            files.append(self.dto_gen.generate_request(class_dto, all_classes_map, relations))
            files.append(self.dto_gen.generate_response(class_dto, all_classes_map, relations))
            # Service
            files.append(self.service_gen.generate(class_dto, all_classes_map, relations))
            # Controller
            files.append(self.controller_gen.generate(class_dto))

        # 4. Empaquetar todo en un ZIP en memoria
        slug = to_snake_case(self.config.project_name).replace("_", "-")
        zip_buffer = io.BytesIO()
        root_dir = f"backend-{slug}"

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for gf in files:
                full_archive_path = f"{root_dir}/{gf.relative_path}"
                content_bytes = (
                    gf.content.encode("utf-8")
                    if isinstance(gf.content, str)
                    else gf.content
                )
                zip_file.writestr(full_archive_path, content_bytes)

        zip_bytes = zip_buffer.getvalue()
        filename = f"{root_dir}.zip"

        return GeneratedSpringBootArchive(
            filename=filename,
            zip_bytes=zip_bytes,
            total_files=len(files),
        )
