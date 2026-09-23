"""Caso de uso para exportar un proyecto a formato XMI 2.1 compatible con Enterprise Architect."""

from dataclasses import dataclass
import re
import unicodedata
from uuid import UUID

from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramSnapshotReader,
)
from app.modules.projects.application.services.xmi_project_exporter import (
    XmiProjectExporter,
)


def sanitize_filename(name: str) -> str:
    """Normaliza y sanitiza el nombre de archivo para la descarga."""
    normalized = (
        unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("ASCII")
    )
    cleaned = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    cleaned = re.sub(r"[-\s]+", "_", cleaned)
    return cleaned or "proyecto"


@dataclass(frozen=True)
class ExportProjectCommand:
    """Comando para exportar un proyecto a archivo XMI."""

    project_id: UUID
    user_id: str


@dataclass(frozen=True)
class ExportProjectResult:
    """Resultado de la exportación conteniendo el nombre sugerido y el contenido XML."""

    project_name: str
    file_name: str
    xml_content: str


class ExportProjectUseCase:
    """Ejecuta la exportación de un proyecto y su diagrama a XMI 2.1."""

    def __init__(
        self,
        project_access_policy: ProjectAccessPolicy,
        diagram_snapshot_reader: DiagramSnapshotReader,
        exporter: XmiProjectExporter | None = None,
    ) -> None:
        self.project_access_policy = project_access_policy
        self.diagram_snapshot_reader = diagram_snapshot_reader
        self.exporter = exporter or XmiProjectExporter()

    def execute(self, command: ExportProjectCommand) -> ExportProjectResult:
        """Valida permisos de lectura, extrae clases y relaciones y genera el XML XMI."""
        access_context = self.project_access_policy.ensure_read_access(
            project_id=command.project_id,
            user_id=command.user_id,
        )
        project = access_context.project

        classes = (
            self.diagram_snapshot_reader.get_classes_with_attributes_by_project_id(
                command.project_id
            )
        )
        relations = self.diagram_snapshot_reader.get_relations_by_project_id(
            command.project_id
        )

        xml_content = self.exporter.export(
            project_name=project.name,
            classes=classes,
            relations=relations,
        )
        file_name = f"{sanitize_filename(project.name)}.xmi"

        return ExportProjectResult(
            project_name=project.name,
            file_name=file_name,
            xml_content=xml_content,
        )
