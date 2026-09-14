from uuid import UUID
from fastapi import APIRouter, Response, status

from app.core.dependencies import CurrentUser, DBSession, UoWDep
from app.modules.diagram.application.queries.diagram.get_diagram import (
    GetDiagramQuery,
    GetDiagramQueryHandler,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.application.use_cases.diagram_class.create_diagram_class import (
    CreateDiagramClassCommand,
    CreateDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.delete_diagram_class import (
    DeleteDiagramClassCommand,
    DeleteDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.move_diagram_class import (
    MoveDiagramClassCommand,
    MoveDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_class.rename_diagram_class import (
    RenameDiagramClassCommand,
    RenameDiagramClassUseCase,
)
from app.modules.diagram.application.use_cases.diagram_relation.delete_diagram_relation import (
    DeleteDiagramRelationCommand,
    DeleteDiagramRelationUseCase,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)

from app.modules.diagram.infrastructure.api.schemas.diagram_schemas import (
    CreateDiagramClassRequest,
    DiagramAttributeRead,
    DiagramClassRead,
    DiagramRead,
    DiagramRelationBridgeRead,
    DiagramRelationEndpointRead,
    DiagramRelationRead,
    MoveDiagramClassRequest,
    RenameDiagramClassRequest,
)

from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_diagram_snapshot_reader import (
    SQLModelDiagramSnapshotReader,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_attribute_repository import (
    SQLModelDiagramAttributeRepository,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_class_repository import (
    SQLModelDiagramClassRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)

router = APIRouter(tags=["diagram-classes"])


@router.get(
    "/projects/{project_id}/diagram",
    response_model=DiagramRead,
    status_code=status.HTTP_200_OK,
    summary="Obtener el diagrama completo de un proyecto",
)
def get_diagram(
    project_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> DiagramRead:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    reader = SQLModelDiagramSnapshotReader(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    handler = GetDiagramQueryHandler(
        access_policy=policy,
        diagram_snapshot_reader=reader,
    )
    query = GetDiagramQuery(
        project_id=project_id,
        user_id=current_user.user_id,
    )
    snapshot = handler.execute(query)

    return DiagramRead(
        classes=[
            DiagramClassRead(
                id=c.id,
                name=c.name,
                position_x=c.position_x,
                position_y=c.position_y,
                attributes=[
                    DiagramAttributeRead(
                        id=a.id,
                        name=a.name,
                        data_type=a.data_type,
                        position=a.position,
                        is_primary_key=a.is_primary_key,
                        is_nullable=a.is_nullable,
                        is_foreign_key=a.is_foreign_key,
                        referenced_class_id=a.referenced_class_id,
                        relation_id=a.relation_id,
                    )
                    for a in c.attributes
                ],
            )
            for c in snapshot.classes
        ],
        relations=[
            DiagramRelationRead(
                id=r.id,
                name=r.name,
                relation_type=r.relation_type,
                source=DiagramRelationEndpointRead(
                    class_id=r.source.class_id,
                    handle=r.source.handle,
                ),
                target=DiagramRelationEndpointRead(
                    class_id=r.target.class_id,
                    handle=r.target.handle,
                ),
                source_cardinality=r.source_cardinality,
                target_cardinality=r.target_cardinality,
                bridge=DiagramRelationBridgeRead(
                    class_id=r.bridge.class_id,
                    handle=r.bridge.handle,
                )
                if r.bridge
                else None,
            )
            for r in snapshot.relations
        ],
    )


@router.post(
    "/projects/{project_id}/diagram/classes",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    summary="Crear una clase de diagrama y su llave primaria de forma atómica",
)
def create_diagram_class(
    project_id: UUID,
    payload: CreateDiagramClassRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_repo = SQLModelDiagramClassRepository(db)
    diagram_attribute_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = CreateDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_repo,
        diagram_attribute_repository=diagram_attribute_repo,
        uow=uow,
    )
    command = CreateDiagramClassCommand(
        id=payload.id,
        project_id=project_id,
        user_id=current_user.user_id,
        name=payload.name,
        position_x=payload.position_x,
        position_y=payload.position_y,
        primary_attribute_id=payload.primary_attribute.id,
        primary_attribute_name=payload.primary_attribute.name,
    )
    _diagram_class, _attributes, is_created = use_case.execute(command)

    if not is_created:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return Response(status_code=status.HTTP_201_CREATED)


@router.patch(
    "/diagram/classes/{class_id}/position",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mover una clase de diagrama",
)
def move_diagram_class(
    class_id: UUID,
    payload: MoveDiagramClassRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_repo = SQLModelDiagramClassRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = MoveDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_repo,
        uow=uow,
    )
    command = MoveDiagramClassCommand(
        class_id=class_id,
        user_id=current_user.user_id,
        position_x=payload.position_x,
        position_y=payload.position_y,
    )
    use_case.execute(command)


@router.patch(
    "/diagram/classes/{class_id}/name",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Renombrar una clase de diagrama",
)
def rename_diagram_class(
    class_id: UUID,
    payload: RenameDiagramClassRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_repo = SQLModelDiagramClassRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = RenameDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_repo,
        uow=uow,
    )
    command = RenameDiagramClassCommand(
        class_id=class_id,
        user_id=current_user.user_id,
        name=payload.name,
    )
    use_case.execute(command)


@router.delete(
    "/diagram/classes/{class_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar físicamente una clase de diagrama",
)
def delete_diagram_class(
    class_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_repo = SQLModelDiagramClassRepository(db)
    diagram_relation_repo = SQLModelDiagramRelationRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    delete_relation_use_case = DeleteDiagramRelationUseCase(
        access_policy=policy,
        diagram_relation_repository=diagram_relation_repo,
        diagram_class_repository=diagram_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    use_case = DeleteDiagramClassUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_repo,
        diagram_relation_repository=diagram_relation_repo,
        diagram_attribute_repository=diagram_attr_repo,
        delete_diagram_relation_use_case=delete_relation_use_case,
        uow=uow,
    )
    command = DeleteDiagramClassCommand(
        class_id=class_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)



from app.modules.diagram.application.use_cases.diagram_attribute.create_diagram_attribute import (
    CreateDiagramAttributeCommand,
    CreateDiagramAttributeUseCase,
)
from app.modules.diagram.infrastructure.api.schemas.diagram_attribute_schemas import (
    CreateDiagramAttributeRequest,
)


@router.post(
    "/diagram/classes/{class_id}/attributes",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    summary="Crear un atributo secundario en una clase de diagrama",
)
def create_diagram_attribute(
    class_id: UUID,
    payload: CreateDiagramAttributeRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = CreateDiagramAttributeUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    command = CreateDiagramAttributeCommand(
        id=payload.id,
        class_id=class_id,
        user_id=current_user.user_id,
        name=payload.name,
        position=payload.position,
    )
    _attribute, is_created = use_case.execute(command)

    if not is_created:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return Response(status_code=status.HTTP_201_CREATED)


from app.modules.diagram.application.use_cases.diagram_attribute.update_diagram_attribute import (
    UpdateDiagramAttributeCommand,
    UpdateDiagramAttributeUseCase,
)
from app.modules.diagram.domain.entities.diagram_attribute import UNSET
from app.modules.diagram.infrastructure.api.schemas.diagram_attribute_schemas import (
    UpdateDiagramAttributeRequest,
)


@router.patch(
    "/diagram/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Actualizar los detalles editables de un atributo",
)
def update_diagram_attribute(
    attribute_id: UUID,
    payload: UpdateDiagramAttributeRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = UpdateDiagramAttributeUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    command = UpdateDiagramAttributeCommand(
        attribute_id=attribute_id,
        user_id=current_user.user_id,
        name=payload.name if "name" in payload.model_fields_set else UNSET,
        data_type=payload.data_type if "data_type" in payload.model_fields_set else UNSET,
        is_nullable=payload.is_nullable if "is_nullable" in payload.model_fields_set else UNSET,
    )
    use_case.execute(command)


from app.modules.diagram.application.use_cases.diagram_attribute.reposition_diagram_attribute import (
    RepositionDiagramAttributeCommand,
    RepositionDiagramAttributeUseCase,
)
from app.modules.diagram.infrastructure.api.schemas.diagram_attribute_schemas import (
    RepositionDiagramAttributeRequest,
)


@router.patch(
    "/diagram/attributes/{attribute_id}/position",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reposicionar un atributo secundario",
)
def reposition_diagram_attribute(
    attribute_id: UUID,
    payload: RepositionDiagramAttributeRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = RepositionDiagramAttributeUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    command = RepositionDiagramAttributeCommand(
        attribute_id=attribute_id,
        user_id=current_user.user_id,
        target_position=payload.position,
    )
    use_case.execute(command)


from app.modules.diagram.application.use_cases.diagram_attribute.delete_diagram_attribute import (
    DeleteDiagramAttributeCommand,
    DeleteDiagramAttributeUseCase,
)


@router.delete(
    "/diagram/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar físicamente un atributo secundario",
)
def delete_diagram_attribute(
    attribute_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> None:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = DeleteDiagramAttributeUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    command = DeleteDiagramAttributeCommand(
        attribute_id=attribute_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)

from app.modules.diagram.application.use_cases.diagram_relation.create_diagram_relation import (
    CreateDiagramRelationCommand,
    CreateDiagramRelationUseCase,
)
from app.modules.diagram.infrastructure.api.schemas.diagram_relation_schemas import (
    CreateRelationRequest,
)
from app.modules.diagram.infrastructure.persistence.repositories.sqlmodel_diagram_relation_repository import (
    SQLModelDiagramRelationRepository,
)


@router.post(
    "/projects/{project_id}/diagram/relations",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    summary="Crear una relación UML y su materialización atómica",
)
def create_diagram_relation(
    project_id: UUID,
    payload: CreateRelationRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)
    diagram_relation_repo = SQLModelDiagramRelationRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = CreateDiagramRelationUseCase(
        access_policy=policy,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        diagram_relation_repository=diagram_relation_repo,
        uow=uow,
    )
    command = CreateDiagramRelationCommand(
        id=payload.id,
        project_id=project_id,
        user_id=current_user.user_id,
        name=payload.name,
        relation_type=payload.relation_type,
        source_class_id=payload.source.class_id,
        target_class_id=payload.target.class_id,
        source_handle=payload.source.handle,
        target_handle=payload.target.handle,
        source_cardinality=payload.source.cardinality,
        target_cardinality=payload.target.cardinality,
        materialization=payload.materialization.model_dump(),
    )
    _relation, is_created = use_case.execute(command)

    if not is_created:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return Response(status_code=status.HTTP_201_CREATED)


from app.modules.diagram.application.use_cases.diagram_relation.rename_diagram_relation import (
    RenameDiagramRelationCommand,
    RenameDiagramRelationUseCase,
)
from app.modules.diagram.infrastructure.api.schemas.diagram_relation_schemas import (
    RenameRelationRequest,
)


@router.patch(
    "/diagram/relations/{relation_id}/name",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Renombrar una relación de diagrama",
)
def rename_diagram_relation(
    relation_id: UUID,
    payload: RenameRelationRequest,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_relation_repo = SQLModelDiagramRelationRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = RenameDiagramRelationUseCase(
        access_policy=policy,
        diagram_relation_repository=diagram_relation_repo,
        uow=uow,
    )
    command = RenameDiagramRelationCommand(
        relation_id=relation_id,
        user_id=current_user.user_id,
        name=payload.name,
    )
    use_case.execute(command)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/diagram/relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Eliminar una relación de diagrama y sus artefactos derivados",
)
def delete_diagram_relation(
    relation_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    uow: UoWDep,
) -> Response:
    project_repo = SQLModelProjectRepository(db)
    member_repo = SQLModelProjectMemberRepository(db)
    diagram_class_repo = SQLModelDiagramClassRepository(db)
    diagram_attr_repo = SQLModelDiagramAttributeRepository(db)
    diagram_relation_repo = SQLModelDiagramRelationRepository(db)

    policy = DiagramAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    use_case = DeleteDiagramRelationUseCase(
        access_policy=policy,
        diagram_relation_repository=diagram_relation_repo,
        diagram_class_repository=diagram_class_repo,
        diagram_attribute_repository=diagram_attr_repo,
        uow=uow,
    )
    command = DeleteDiagramRelationCommand(
        relation_id=relation_id,
        user_id=current_user.user_id,
    )
    use_case.execute(command)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

