import uuid
import pytest
from sqlmodel import Session

from app.core.security.auth import AuthUser
from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser


@pytest.fixture
def owner_user() -> AuthUser:
    return AuthUser(user_id="user_owner", email="owner@test.com")


@pytest.fixture
def editor_user() -> AuthUser:
    return AuthUser(user_id="user_editor", email="editor@test.com")


@pytest.fixture
def reader_user() -> AuthUser:
    return AuthUser(user_id="user_reader", email="reader@test.com")


@pytest.fixture
def removed_user() -> AuthUser:
    return AuthUser(user_id="user_removed", email="removed@test.com")


@pytest.fixture
def banned_user() -> AuthUser:
    return AuthUser(user_id="user_banned", email="banned@test.com")


@pytest.fixture
def stranger_user() -> AuthUser:
    return AuthUser(user_id="user_stranger", email="stranger@test.com")


@pytest.fixture
def test_project(
    session: Session,
    owner_user: AuthUser,
    editor_user: AuthUser,
    reader_user: AuthUser,
    removed_user: AuthUser,
    banned_user: AuthUser,
    stranger_user: AuthUser,
) -> ProjectModel:
    # Registrar usuarios en BetterAuth si no existen
    users = [
        BetterAuthUser(id=owner_user.user_id, name="Propietario", email=owner_user.email),
        BetterAuthUser(id=editor_user.user_id, name="Editor", email=editor_user.email),
        BetterAuthUser(id=reader_user.user_id, name="Lector", email=reader_user.email),
        BetterAuthUser(id=removed_user.user_id, name="Removido", email=removed_user.email),
        BetterAuthUser(id=banned_user.user_id, name="Baneado", email=banned_user.email),
        BetterAuthUser(id=stranger_user.user_id, name="Extrano", email=stranger_user.email),
    ]
    for u in users:
        existing = session.get(BetterAuthUser, u.id)
        if not existing:
            session.add(u)
    session.flush()

    # Crear proyecto
    project = ProjectModel(
        id=uuid.uuid4(),
        owner_id=owner_user.user_id,
        name="Proyecto de Diagrama",
        description="Proyecto para pruebas de clases",
    )
    session.add(project)
    session.flush()

    # Crear miembros
    members = [
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=editor_user.user_id,
            role=ProjectMemberRole.EDITOR,
            status=ProjectMemberStatus.ACTIVE,
        ),
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=reader_user.user_id,
            role=ProjectMemberRole.READER,
            status=ProjectMemberStatus.ACTIVE,
        ),
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=removed_user.user_id,
            role=ProjectMemberRole.READER,
            status=ProjectMemberStatus.REMOVED,
        ),
        ProjectMemberModel(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=banned_user.user_id,
            role=ProjectMemberRole.READER,
            status=ProjectMemberStatus.BANNED,
        ),
    ]
    for m in members:
        session.add(m)

    session.commit()
    session.refresh(project)
    return project


from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)


def create_test_class(
    session: Session,
    project_id: uuid.UUID,
    name: str = "TestClass",
    position_x: float = 0.0,
    position_y: float = 0.0,
    class_id: uuid.UUID | None = None,
) -> DiagramClassModel:
    """Helper para crear una clase de diagrama directamente en base de datos."""
    cls_model = DiagramClassModel(
        id=class_id or uuid.uuid4(),
        project_id=project_id,
        name=name,
        position_x=position_x,
        position_y=position_y,
    )
    session.add(cls_model)
    session.flush()
    return cls_model


def create_test_attribute(
    session: Session,
    class_id: uuid.UUID,
    name: str = "id",
    data_type: str | None = "UUID",
    position: int = 0,
    is_primary_key: bool = True,
    is_nullable: bool = False,
    is_foreign_key: bool = False,
    referenced_class_id: uuid.UUID | None = None,
    relation_id: uuid.UUID | None = None,
    attr_id: uuid.UUID | None = None,
) -> DiagramAttributeModel:
    """Helper para crear un atributo de diagrama directamente en base de datos."""
    kwargs = {
        "id": attr_id or uuid.uuid4(),
        "class_id": class_id,
        "name": name,
        "data_type": data_type,
        "position": position,
        "is_primary_key": is_primary_key,
        "is_nullable": is_nullable,
    }
    if hasattr(DiagramAttributeModel, "is_foreign_key"):
        kwargs["is_foreign_key"] = is_foreign_key
        kwargs["referenced_class_id"] = referenced_class_id
        kwargs["relation_id"] = relation_id
    attr_model = DiagramAttributeModel(**kwargs)
    session.add(attr_model)
    session.flush()
    return attr_model


def create_test_relation(
    session: Session,
    project_id: uuid.UUID,
    source_class_id: uuid.UUID,
    target_class_id: uuid.UUID,
    relation_type: str = "ASSOCIATION",
    name: str = "Nueva relación",
    source_cardinality: str | None = "1",
    target_cardinality: str | None = "0..*",
    source_handle: str = "RIGHT_CENTER",
    target_handle: str = "LEFT_CENTER",
    bridge_class_id: uuid.UUID | None = None,
    bridge_handle: str | None = None,
    relation_id: uuid.UUID | None = None,
):
    """Helper para crear una relación de diagrama directamente en base de datos."""
    from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
        DiagramRelationModel,
    )

    rel_model = DiagramRelationModel(
        id=relation_id or uuid.uuid4(),
        project_id=project_id,
        source_class_id=source_class_id,
        target_class_id=target_class_id,
        relation_type=relation_type,
        name=name,
        source_cardinality=source_cardinality,
        target_cardinality=target_cardinality,
        source_handle=source_handle,
        target_handle=target_handle,
        bridge_class_id=bridge_class_id,
        bridge_handle=bridge_handle,
    )
    session.add(rel_model)
    session.flush()
    return rel_model


@pytest.fixture
def two_classes(session: Session, test_project: ProjectModel) -> tuple[DiagramClassModel, DiagramClassModel]:
    """Fixture que proporciona dos clases con claves primarias creadas en el mismo proyecto."""
    cls_a = create_test_class(session, test_project.id, name="ClaseOrigen", position_x=100.0, position_y=100.0)
    create_test_attribute(session, class_id=cls_a.id, name="id", is_primary_key=True, is_nullable=False, position=0)
    cls_b = create_test_class(session, test_project.id, name="ClaseDestino", position_x=400.0, position_y=100.0)
    create_test_attribute(session, class_id=cls_b.id, name="id", is_primary_key=True, is_nullable=False, position=0)
    session.commit()
    session.refresh(cls_a)
    session.refresh(cls_b)
    return cls_a, cls_b


@pytest.fixture
def test_class(session: Session, test_project: ProjectModel) -> DiagramClassModel:
    """Fixture que proporciona una clase con su clave primaria ya creada."""
    cls_model = create_test_class(session, test_project.id, name="Usuario")
    create_test_attribute(
        session,
        class_id=cls_model.id,
        name="id",
        data_type="UUID",
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    session.commit()
    session.refresh(cls_model)
    return cls_model


@pytest.fixture
def test_class_with_attributes(
    session: Session, test_class: DiagramClassModel
) -> DiagramClassModel:
    """Fixture que proporciona una clase con clave primaria y atributos secundarios."""
    create_test_attribute(
        session,
        class_id=test_class.id,
        name="nombre",
        data_type="TEXT",
        position=1,
        is_primary_key=False,
        is_nullable=True,
    )
    create_test_attribute(
        session,
        class_id=test_class.id,
        name="edad",
        data_type="INTEGER",
        position=2,
        is_primary_key=False,
        is_nullable=True,
    )
    create_test_attribute(
        session,
        class_id=test_class.id,
        name="activo",
        data_type="BOOLEAN",
        position=3,
        is_primary_key=False,
        is_nullable=True,
    )
    session.commit()
    session.refresh(test_class)
    return test_class
