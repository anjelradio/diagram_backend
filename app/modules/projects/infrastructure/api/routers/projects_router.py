from uuid import UUID
from fastapi import APIRouter, File, Response, UploadFile, status

from app.core.dependencies import CurrentUser, DBSession, UoWDep
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)
from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_diagram_snapshot_reader import (
    SQLModelDiagramSnapshotReader,
)
from app.modules.projects.application.queries.project.get_project import (
    GetProjectQuery,
    GetProjectQueryHandler,
)
from app.modules.projects.application.queries.project.list_projects import (
    ListProjectsQuery,
    ListProjectsQueryHandler,
)
from app.modules.projects.application.use_cases.project.create_project import (
    CreateProjectCommand,
    CreateProjectUseCase,
)
from app.modules.projects.application.use_cases.project.delete_project import (
    DeleteProjectCommand,
    DeleteProjectUseCase,
)
from app.modules.projects.application.use_cases.project.export_project import (
    ExportProjectCommand,
    ExportProjectUseCase,
)
from app.modules.projects.application.use_cases.project.import_project import (
    ImportProjectCommand,
    ImportProjectUseCase,
)
from app.modules.projects.application.use_cases.project.update_project import (
    UpdateProjectCommand,
    UpdateProjectUseCase,
)
from app.modules.projects.infrastructure.api.schemas.project_schemas import (
    ProjectCreatedResponse,
    ProjectDetailResponse,
    ProjectItemResponse,
    ProjectListResponse,
    UpdateProjectRequest,
)
from app.modules.projects.infrastructure.persistence.readers.sqlmodel_project_list_reader import (
    SQLModelProjectListReader,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un proyecto en blanco",
)
def create_project(
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> ProjectCreatedResponse:
    """Crea un proyecto vacío con nombre por defecto y retorna su identificador único."""
    repository = SQLModelProjectRepository(db)
    use_case = CreateProjectUseCase(project_repository=repository, uow=uow)
    command = CreateProjectCommand(owner_id=current_user.user_id)
    project_id = use_case.execute(command)

    return ProjectCreatedResponse(id=project_id)


@router.post(
    "/import",
    response_model=ProjectCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Importar un proyecto desde archivo XML/XMI compatible con Enterprise Architect",
)
async def import_project(
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
    file: UploadFile = File(...),
) -> ProjectCreatedResponse:
    """Importa un proyecto desde un archivo XMI/XML y crea sus clases, atributos y relaciones."""
    content = await file.read()
    project_repo = SQLModelProjectRepository(db)
    class_repo = SQLModelDiagramClassRepository(db)
    attr_repo = SQLModelDiagramAttributeRepository(db)
    rel_repo = SQLModelDiagramRelationRepository(db)

    use_case = ImportProjectUseCase(
        project_repository=project_repo,
        diagram_class_repository=class_repo,
        diagram_attribute_repository=attr_repo,
        diagram_relation_repository=rel_repo,
        uow=uow,
    )
    project_id = use_case.execute(
        ImportProjectCommand(user_id=current_user.user_id, xml_content=content)
    )
    return ProjectCreatedResponse(id=project_id)


@router.get(
    "",
    response_model=ProjectListResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar proyectos del usuario",
)
def list_projects(
    current_user: CurrentUser,
    db: DBSession,
) -> ProjectListResponse:
    """Retorna los proyectos propios y las participaciones activas del usuario autenticado."""
    reader = SQLModelProjectListReader(db)
    handler = ListProjectsQueryHandler(project_list_reader=reader)
    query = ListProjectsQuery(user_id=current_user.user_id)
    dto = handler.execute(query)

    return ProjectListResponse(
        items=[
            ProjectItemResponse(
                id=item.id,
                name=item.name,
                description=item.description,
                thumbnail_url=item.thumbnail_url,
                is_owner=item.is_owner,
            )
            for item in dto.items
        ]
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener un proyecto y su rol de acceso resuelto",
)
def get_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> ProjectDetailResponse:
    """Retorna los datos del proyecto y el rol resuelto (OWNER, EDITOR, READER).

    Si el proyecto no existe, está eliminado lógicamente o el usuario no tiene acceso activo,
    falla cerrado retornando 404 (ProjectNotFoundException).
    """
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    access_policy = ProjectAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    handler = GetProjectQueryHandler(access_policy=access_policy)
    dto = handler.execute(
        GetProjectQuery(project_id=project_id, user_id=current_user.user_id)
    )

    return ProjectDetailResponse(
        id=dto.id,
        name=dto.name,
        description=dto.description,
        thumbnail_url=dto.thumbnail_url,
        access_role=dto.access_role,
    )


@router.patch(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Actualizar información de un proyecto",
)
def update_project(
    project_id: UUID,
    payload: UpdateProjectRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Actualiza parcialmente los datos del proyecto. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    use_case = UpdateProjectUseCase(project_repository=project_repo, uow=uow)
    command = UpdateProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
        name=payload.name,
        description=payload.description,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar lógicamente un proyecto",
)
def delete_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Marca el proyecto como eliminado lógicamente. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    use_case = DeleteProjectUseCase(project_repository=project_repo, uow=uow)
    command = DeleteProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{project_id}/export",
    status_code=status.HTTP_200_OK,
    summary="Exportar diagrama de proyecto a archivo XMI 2.1 compatible con Enterprise Architect",
    responses={
        200: {
            "content": {"application/xml": {}},
            "description": "Archivo XML/XMI con diagrama descargable.",
        }
    },
)
def export_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> Response:
    """Genera y descarga el archivo XML/XMI del proyecto."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    access_policy = ProjectAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    snapshot_reader = SQLModelDiagramSnapshotReader(db)
    use_case = ExportProjectUseCase(
        project_access_policy=access_policy,
        diagram_snapshot_reader=snapshot_reader,
    )

    command = ExportProjectCommand(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    result = use_case.execute(command)

    return Response(
        content=result.xml_content,
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result.file_name}"',
        },
    )


@router.get(
    "/{project_id}/assistant/activities",
    status_code=status.HTTP_200_OK,
    summary="Listar historial de actividades del asistente (alias en /api/projects)",
)
def list_project_activities_alias(
    project_id: UUID,
    current_user: CurrentUser = None,
    uow: UoWDep = None,
):
    from app.modules.assistant.infrastructure.api.routers.assistant_router import (
        list_project_activities,
    )

    return list_project_activities(
        project_id=project_id,
        current_user=current_user,
        uow=uow,
    )
