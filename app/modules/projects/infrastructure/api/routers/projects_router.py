from uuid import UUID
from fastapi import APIRouter, status, Response

from app.core.config import settings
from app.core.dependencies import CurrentUser, DBSession, UoWDep
from app.modules.projects.application.queries.project.get_project import (
    GetProjectQuery,
    GetProjectQueryHandler,
)
from app.modules.projects.application.queries.project.list_projects import (
    ListProjectsQuery,
    ListProjectsQueryHandler,
)
from app.modules.projects.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.projects.application.use_cases.invitation.create_or_refresh_invitation import (
    CreateOrRefreshInvitationCommand,
    CreateOrRefreshInvitationUseCase,
)
from app.modules.projects.application.use_cases.project.create_project import (
    CreateProjectCommand,
    CreateProjectUseCase,
)
from app.modules.projects.application.use_cases.project.delete_project import (
    DeleteProjectCommand,
    DeleteProjectUseCase,
)
from app.modules.projects.application.use_cases.project.update_project import (
    UpdateProjectCommand,
    UpdateProjectUseCase,
)
from app.modules.projects.application.use_cases.project_member.join_project_by_code import (
    JoinProjectByCodeCommand,
    JoinProjectByCodeUseCase,
)
from app.modules.projects.infrastructure.api.schemas.invitation_schemas import (
    InvitationResponse,
    JoinProjectRequest,
    JoinProjectResponse,
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
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_invitation_repository import (
    SQLModelInvitationRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
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


@router.post(
    "/join",
    response_model=JoinProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Unirse a un proyecto mediante código",
)
def join_project(
    payload: JoinProjectRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> JoinProjectResponse:
    """Valida el código de invitación e incorpora al usuario como colaborador lector."""
    project_repo = SQLModelProjectRepository(db)
    invitation_repo = SQLModelInvitationRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)

    use_case = JoinProjectByCodeUseCase(
        project_repository=project_repo,
        invitation_repository=invitation_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = JoinProjectByCodeCommand(code=payload.code, user_id=current_user.user_id)
    result = use_case.execute(command)

    return JoinProjectResponse(project_id=result.project_id)



@router.post(
    "/{project_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar o reutilizar invitación a un proyecto",
)
def create_or_refresh_invitation(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> InvitationResponse:
    """Devuelve la invitación activa o genera un nuevo código temporal si ha vencido."""
    project_repo = SQLModelProjectRepository(db)
    invitation_repo = SQLModelInvitationRepository(db)

    use_case = CreateOrRefreshInvitationUseCase(
        project_repository=project_repo,
        invitation_repository=invitation_repo,
        uow=uow,
        expiration_days=settings.INVITATION_EXPIRATION_DAYS,
    )
    command = CreateOrRefreshInvitationCommand(
        project_id=project_id, user_id=current_user.user_id
    )
    dto = use_case.execute(command)

    return InvitationResponse(code=dto.code, expires_at=dto.expires_at)


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

