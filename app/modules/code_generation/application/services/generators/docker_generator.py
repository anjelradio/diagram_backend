import json
from pathlib import Path
from uuid import UUID

from app.modules.code_generation.application.services.generators.capabilities_generator import (
    _get_dummy_value,
)
from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    sanitize_class_attributes,
    to_camel_case,
    to_kebab_case,
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


class DockerAndConfigGenerator:
    """Generador de archivos Docker, configuracion de Spring Boot, README.md y API_REFERENCE.md."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config
        self.templates_dir = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "infrastructure"
            / "templates"
            / "spring_boot"
        )

    def _render_template(self, filename: str, context: dict[str, str]) -> str:
        template_path = self.templates_dir / f"{filename}.template"
        content = template_path.read_text(encoding="utf-8")
        for key, val in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(val))
        return content

    def generate_api_reference(
        self,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto] | None = None,
    ) -> GeneratedFile:
        all_classes_map: dict[UUID, DiagramClassSnapshotDto] = {
            c.id: c for c in classes
        }
        relations = relations or []

        lines = [
            f"# Referencia de API y Payloads: {self.config.project_name}",
            "",
            "Guia de integracion, endpoints y contratos para desarrolladores y asistentes de Inteligencia Artificial.",
            "",
            "## 1. Caracteristicas Principales",
            f"- **URL Base**: `http://localhost:{self.config.server_port}`",
            "- **Documentacion Interactiva (Swagger/OpenAPI)**: [`/swagger-ui.html`](http://localhost:8080/swagger-ui.html)",
            "- **Esquema Machine-Readable para IA**: Ver archivo `capabilities.json` (v2.0.0 compacto) en la raiz del proyecto.",
            "- **Esquema Espejo SQLite (Flutter)**: Ver archivo `schema.sql` en la raiz del proyecto con DDL adaptado para SQLite en aplicaciones locales.",
            "- **Identidad Mobile-First (UUID v4)**: Los endpoints `POST` aceptan opcionalmente un campo `id` con un UUID generado por el cliente movil para soporte offline. Si se omite, el servidor genera el UUID automaticamente.",
            '- **Respuestas Encapsuladas en `{"message": "..."}`**: Todas las mutaciones (`POST`, `PUT`, `DELETE`) y errores de validacion responden exclusivamente con un mensaje conciso en espanol sin jerga tecnica de base de datos.',
            "",
            "## 2. Convencion de Repositorios en Spring Data JPA",
            "> Las interfaces de repositorio (ej. `ProductoRepository.java`) se encuentran intencionalmente sin metodos declarados. En Spring Data JPA, heredar de `JpaRepository<Entity, UUID>` provee en tiempo de ejecucion todas las operaciones CRUD estandar (`save`, `findById`, `findAll`, `deleteById`, etc.). Solo se agregan metodos explicitos cuando se requieren consultas o filtros personalizados.",
            "",
            "## 3. Endpoints y Ejemplos de Payloads por Entidad",
            "",
        ]

        for c in classes:
            cname = to_pascal_case(c.name)
            kebab = to_kebab_case(c.name)
            sanitized_attrs = sanitize_class_attributes(c.attributes)
            pk_attr = next(sa for sa in sanitized_attrs if sa.is_primary_key)
            non_pk_attrs = [sa for sa in sanitized_attrs if not sa.is_primary_key]

            # Relaciones ManyToOne legítimas resueltas
            deps = resolve_entity_dependencies(c, all_classes_map, relations)
            rel_fields = []
            for dep in deps:
                rel_fields.append({
                    "name": dep.fk_field_name,
                    "label": dep.label,
                    "is_nullable": dep.is_nullable,
                })

            create_payload = {}
            if pk_attr.java_type == "UUID":
                create_payload["id"] = "c56a4180-65aa-42ec-a945-5fd21dec0538 (opcional si es mobile-first)"

            for sa in non_pk_attrs:
                create_payload[sa.field_name] = _get_dummy_value(sa.java_type, sa.field_name)

            for rf in rel_fields:
                create_payload[rf["name"]] = "a12b34cd-56ef-7890-abcd-ef1234567890 (UUID de " + rf["label"] + ")"

            update_payload = {k: v for k, v in create_payload.items() if k != "id"}

            lines.extend([
                f"### Entidad: `{cname}`",
                f"- **Ruta Base**: `/api/{kebab}`",
                "",
                f"#### `GET /api/{kebab}`",
                f"- **Descripcion**: Lista todos los registros de `{cname}`.",
                "- **Respuesta**: HTTP 200 OK `[ ... ]`",
                "",
                f"#### `GET /api/{kebab}/{{id}}`",
                f"- **Descripcion**: Obtiene el registro de `{cname}` por su ID.",
                f'- **Respuesta**: HTTP 200 OK `{{ ... }}` (o HTTP 404 `{{"message": "{cname} no encontrado"}}`)',
                "",
                f"#### `POST /api/{kebab}`",
                f"- **Descripcion**: Crea y registra un nuevo `{cname}`.",
                "- **Ejemplo de Payload JSON (Request Body)**:",
                "```json",
                json.dumps(create_payload, indent=2, ensure_ascii=False),
                "```",
                "- **Respuestas Posibles**:",
                f'  - HTTP 201 Created: `{{"message": "{cname} registrado correctamente"}}`',
            ])

            for rf in rel_fields:
                if not rf.get("is_nullable", False):
                    lines.append(f'  - HTTP 400 Bad Request (si falta relacion): `{{"message": "{rf["label"]} obligatoria"}}`')
                lines.append(f'  - HTTP 400 Bad Request (si no existe relacion): `{{"message": "{rf["label"]} no encontrada"}}`')

            lines.extend([
                "",
                f"#### `PUT /api/{kebab}/{{id}}`",
                f"- **Descripcion**: Actualiza un registro existente de `{cname}`.",
                "- **Ejemplo de Payload JSON (Request Body)**:",
                "```json",
                json.dumps(update_payload, indent=2, ensure_ascii=False),
                "```",
                "- **Respuesta**:",
                f'  - HTTP 200 OK: `{{"message": "{cname} actualizado correctamente"}}`',
                f'  - HTTP 404 Not Found: `{{"message": "{cname} no encontrado"}}`',
                "",
                f"#### `DELETE /api/{kebab}/{{id}}`",
                f"- **Descripcion**: Elimina un registro de `{cname}` por su ID.",
                "- **Respuesta**:",
                f'  - HTTP 200 OK: `{{"message": "{cname} eliminado correctamente"}}`',
                f'  - HTTP 404 Not Found: `{{"message": "{cname} no encontrado"}}`',
                "",
                "---",
                "",
            ])

        return GeneratedFile(
            relative_path="API_REFERENCE.md",
            content="\n".join(lines),
        )

    def generate_all(
        self,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto] | None = None,
    ) -> list[GeneratedFile]:
        context = {
            "project_name": self.config.project_name,
            "artifact_id": self.config.artifact_id,
            "group_id": self.config.group_id,
            "package_name": self.config.package_name,
            "java_version": self.config.java_version,
            "spring_boot_version": self.config.spring_boot_version,
            "database_name": self.config.database_name,
            "database_username": self.config.database_username,
            "database_password": self.config.database_password,
            "server_port": str(self.config.server_port),
        }

        endpoints = []
        for c in classes:
            cname = to_pascal_case(c.name)
            kebab = to_kebab_case(c.name)
            endpoints.append(
                f"### {cname} (`/api/{kebab}`)\n"
                f"- `GET /api/{kebab}`: Listar todos los registros.\n"
                f"- `GET /api/{kebab}/{{id}}`: Obtener un registro por ID.\n"
                f"- `POST /api/{kebab}`: Crear nuevo registro.\n"
                f"- `PUT /api/{kebab}/{{id}}`: Actualizar registro existente.\n"
                f"- `DELETE /api/{kebab}/{{id}}`: Eliminar registro por ID.\n"
            )
        context["endpoints_summary"] = "\n".join(endpoints)

        files = []

        # 1. pom.xml
        files.append(
            GeneratedFile(
                relative_path="pom.xml",
                content=self._render_template("pom.xml", context),
            )
        )

        # 2. application.properties
        files.append(
            GeneratedFile(
                relative_path="src/main/resources/application.properties",
                content=self._render_template("application.properties", context),
            )
        )

        # 3. Application.java
        package_path = self.config.package_name.replace(".", "/")
        files.append(
            GeneratedFile(
                relative_path=f"src/main/java/{package_path}/Application.java",
                content=self._render_template("Application.java", context),
            )
        )

        # 4. Dockerfile
        files.append(
            GeneratedFile(
                relative_path="Dockerfile",
                content=self._render_template("Dockerfile", context),
            )
        )

        # 5. docker-compose.yml
        files.append(
            GeneratedFile(
                relative_path="docker-compose.yml",
                content=self._render_template("docker-compose.yml", context),
            )
        )

        # 6. .dockerignore
        files.append(
            GeneratedFile(
                relative_path=".dockerignore",
                content=self._render_template(".dockerignore", context),
            )
        )

        # 7. README.md
        files.append(
            GeneratedFile(
                relative_path="README.md",
                content=self._render_template("README.md", context),
            )
        )

        # 8. API_REFERENCE.md
        files.append(self.generate_api_reference(classes, relations))

        return files
