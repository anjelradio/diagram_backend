import uuid
import os
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text

from app.core.security.auth import AuthUser
from app.modules.collaboration.domain.enums.project_member_role import ProjectMemberRole
from app.modules.collaboration.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import (
    ProjectMemberModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)
from app.shared.infrastructure.db.better_auth import BetterAuthUser
from tests.modules.diagram.conftest import (  # noqa: F401
    banned_user,
    editor_user,
    owner_user,
    reader_user,
    removed_user,
    stranger_user,
    test_project,
)


@pytest.fixture
def assistant_postgres_engine():
    """Base PostgreSQL aislada en un esquema temporal para pruebas de carrera."""
    database_url = os.getenv("ASSISTANT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "PostgreSQL de assistant no configurado; define ASSISTANT_TEST_DATABASE_URL "
            "para validar concurrencia real."
        )
    if os.getenv("ASSISTANT_TEST_DATABASE_ISOLATED", "").lower() != "true":
        pytest.skip(
            "No se confirmó aislamiento; define ASSISTANT_TEST_DATABASE_ISOLATED=true "
            "para usar un esquema temporal desechable."
        )

    base_engine = create_engine(database_url, pool_size=20, max_overflow=0, pool_pre_ping=True)
    schema_name = f"assistant_test_{uuid.uuid4().hex}"
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    isolated_engine = base_engine.execution_options(
        schema_translate_map={None: schema_name}
    )
    SQLModel.metadata.create_all(isolated_engine)
    try:
        yield isolated_engine
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        base_engine.dispose()


@pytest.fixture
def second_editor_user() -> AuthUser:
    return AuthUser(user_id="user_editor_2", email="editor2@test.com")


@pytest.fixture
def collaborative_project(
    session: Session,
    owner_user: AuthUser,
    editor_user: AuthUser,
    second_editor_user: AuthUser,
    reader_user: AuthUser,
) -> ProjectModel:
    users = [
        BetterAuthUser(id=owner_user.user_id, name="Owner", email=owner_user.email),
        BetterAuthUser(id=editor_user.user_id, name="Editor 1", email=editor_user.email),
        BetterAuthUser(id=second_editor_user.user_id, name="Editor 2", email=second_editor_user.email),
        BetterAuthUser(id=reader_user.user_id, name="Reader", email=reader_user.email),
    ]
    for u in users:
        existing = session.get(BetterAuthUser, u.id)
        if not existing:
            session.add(u)
    session.flush()

    project = ProjectModel(
        id=uuid.uuid4(),
        owner_id=owner_user.user_id,
        name="Proyecto Colaborativo",
        description="Proyecto con multiples editores",
    )
    session.add(project)
    session.flush()

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
            user_id=second_editor_user.user_id,
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
    ]
    for m in members:
        session.add(m)

    session.commit()
    session.refresh(project)
    return project


@pytest.fixture
def sample_confirmed_entity_refs() -> list[dict[str, str]]:
    """Referencias confirmadas y normalizadas de entidades de diagrama."""
    return [
        {"type": "class", "id": str(uuid.uuid4()), "name": "Cliente"},
        {"type": "attribute", "id": str(uuid.uuid4()), "name": "email"},
        {"type": "relation", "id": str(uuid.uuid4()), "name": "asociacion_cliente_pedido"},
    ]


@pytest.fixture
def sample_uncertain_result() -> dict[str, object]:
    """Resultado incierto de mutación que no debe ser reintentado automáticamente."""
    return {
        "status": "uncertain",
        "error": "Error de commit: resultado incierto",
        "entity_refs": [],
        "results": [],
    }


@pytest.fixture
def sample_compound_plan_payload() -> dict[str, object]:
    """Carga útil de plan compuesto para pruebas deterministas."""
    return {
        "goal": "Crear Autor y Libro con relación N:M y atributo puente",
        "tasks": [
            {"id": "t-autor", "objective": "Crear clase Autor", "kind": "mutation", "depends_on": []},
            {"id": "t-libro", "objective": "Crear clase Libro", "kind": "mutation", "depends_on": []},
            {"id": "t-rel", "objective": "Relacionar Autor y Libro", "kind": "mutation", "depends_on": ["t-autor", "t-libro"]},
            {"id": "t-bridge-attr", "objective": "Añadir atributo a la tabla intermedia", "kind": "mutation", "depends_on": ["t-rel"]},
        ],
    }


@pytest.fixture
def sample_execution_plan(sample_compound_plan_payload: dict[str, object]):
    """Instancia de dominio de ExecutionPlan determinista."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    return ExecutionPlan.create(
        goal=str(sample_compound_plan_payload["goal"]),
        tasks=list(sample_compound_plan_payload["tasks"]),  # type: ignore[arg-type]
        limits={"max_tasks": 10},
    )


@pytest.fixture
def sample_uncertain_execution_plan(sample_compound_plan_payload: dict[str, object]):
    """ExecutionPlan con operación y tarea en estado incierto."""
    from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan

    plan = ExecutionPlan.create(
        goal=str(sample_compound_plan_payload["goal"]),
        tasks=list(sample_compound_plan_payload["tasks"]),  # type: ignore[arg-type]
    )
    plan.tasks[0]["status"] = "uncertain"
    plan.status = "uncertain"
    plan.operation_ledger.append(
        {
            "operation_id": "op-uncertain-1",
            "task_id": "t-autor",
            "tool": "apply_diagram_changes",
            "status": "uncertain",
            "entity_refs": [],
            "error": "Conexión interrumpida durante commit",
        }
    )
    plan.validate()
    return plan

