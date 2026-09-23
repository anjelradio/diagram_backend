from uuid import UUID
from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.dependencies import CurrentUser, DBSession, UoWDep
from app.modules.collaboration.application.queries.project_member.list_project_members import (
    ListProjectMembersQuery,
    ListProjectMembersQueryHandler,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.application.use_cases.invitation.create_or_refresh_invitation import (
    CreateOrRefreshInvitationCommand,
    CreateOrRefreshInvitationUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.ban_project_member import (
    BanProjectMemberCommand,
    BanProjectMemberUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.demote_project_member import (
    DemoteProjectMemberCommand,
    DemoteProjectMemberUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.join_project_by_code import (
    JoinProjectByCodeCommand,
    JoinProjectByCodeUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.promote_project_member import (
    PromoteProjectMemberCommand,
    PromoteProjectMemberUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.remove_project_member import (
    RemoveProjectMemberCommand,
    RemoveProjectMemberUseCase,
)
from app.modules.collaboration.application.use_cases.project_member.unban_project_member import (
    UnbanProjectMemberCommand,
    UnbanProjectMemberUseCase,
)
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.api.schemas.invitation_schemas import (
    InvitationResponse,
    JoinProjectRequest,
    JoinProjectResponse,
)
from app.modules.collaboration.infrastructure.api.schemas.project_member_schemas import (
    MemberItemResponse,
    MemberListResponse,
)
from app.modules.collaboration.infrastructure.persistence.readers.sqlmodel_project_member_list_reader import (
    SQLModelProjectMemberListReader,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_invitation_repository import (
    SQLModelInvitationRepository,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(prefix="/projects", tags=["Collaboration"])


# ==============================================================================
# INVITACIONES Y UNIÓN
# ==============================================================================


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


# ==============================================================================
# GESTIÓN DE MIEMBROS
# ==============================================================================


@router.get(
    "/{project_id}/members",
    response_model=MemberListResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar colaboradores de un proyecto",
)
def list_project_members(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    status_filter: ProjectMemberStatus | None = None,
) -> MemberListResponse:
    """Retorna los colaboradores del proyecto con sus datos de usuario, filtrables por estado."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    access_policy = ProjectAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    reader = SQLModelProjectMemberListReader(db)
    handler = ListProjectMembersQueryHandler(
        access_policy=access_policy,
        project_member_list_reader=reader,
    )
    query = ListProjectMembersQuery(
        project_id=project_id,
        user_id=current_user.user_id,
        status=status_filter,
    )
    dto = handler.execute(query)

    return MemberListResponse(
        items=[
            MemberItemResponse(
                id=item.id,
                user_id=item.user_id,
                name=item.name,
                email=item.email,
                image=item.image,
                role=item.role,
                status=item.status,
            )
            for item in dto.items
        ]
    )


@router.post(
    "/{project_id}/members/{member_id}/promote",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Promover colaborador a rol EDITOR",
)
def promote_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Asigna el rol EDITOR al colaborador. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    use_case = PromoteProjectMemberUseCase(
        project_repository=project_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = PromoteProjectMemberCommand(
        project_id=project_id,
        member_id=member_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/members/{member_id}/demote",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Degradar colaborador a rol READER",
)
def demote_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Asigna el rol READER al colaborador. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    use_case = DemoteProjectMemberUseCase(
        project_repository=project_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = DemoteProjectMemberCommand(
        project_id=project_id,
        member_id=member_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/members/{member_id}/remove",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover colaborador del proyecto",
)
def remove_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Cambia el estado del colaborador a REMOVED. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    use_case = RemoveProjectMemberUseCase(
        project_repository=project_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = RemoveProjectMemberCommand(
        project_id=project_id,
        member_id=member_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/members/{member_id}/ban",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bloquear colaborador en el proyecto",
)
def ban_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Bloquea al colaborador (BANNED), impidiendo su reingreso. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    use_case = BanProjectMemberUseCase(
        project_repository=project_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = BanProjectMemberCommand(
        project_id=project_id,
        member_id=member_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/members/{member_id}/unban",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desbloquear colaborador en el proyecto",
)
def unban_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    """Desbloquea al colaborador restaurándolo a ACTIVE. Solo permitido para el propietario."""
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    use_case = UnbanProjectMemberUseCase(
        project_repository=project_repo,
        project_member_repository=member_repo,
        uow=uow,
    )
    command = UnbanProjectMemberCommand(
        project_id=project_id,
        member_id=member_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
