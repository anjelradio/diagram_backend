import io
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import CurrentUser, DBSession
from app.modules.code_generation.application.use_cases.generate_spring_boot_project import (
    GenerateSpringBootProjectCommand,
    GenerateSpringBootProjectUseCase,
)
from app.modules.code_generation.infrastructure.api.schemas.code_generation_schemas import (
    SpringBootGenerationRequest,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_diagram_snapshot_reader import (
    SQLModelDiagramSnapshotReader,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(prefix="/code-generation", tags=["Code Generation"])


@router.post(
    "/projects/{project_id}/spring-boot",
    summary="Generar y descargar backend Spring Boot completo en ZIP",
    status_code=status.HTTP_200_OK,
)
def generate_spring_boot_backend(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    request: SpringBootGenerationRequest | None = None,
) -> StreamingResponse:
    """Genera un proyecto Spring Boot con base de datos PostgreSQL a partir del diagrama actual."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    access_policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    diagram_reader = SQLModelDiagramSnapshotReader(db)

    use_case = GenerateSpringBootProjectUseCase(
        diagram_reader=diagram_reader,
        access_policy=access_policy,
    )

    command = GenerateSpringBootProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
        package_name=request.package_name if request else None,
        artifact_id=request.artifact_id if request else None,
        database_name=request.database_name if request else None,
    )

    archive = use_case.execute(command)

    return StreamingResponse(
        io.BytesIO(archive.zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{archive.filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
