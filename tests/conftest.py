from collections.abc import Iterator
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import app.shared.infrastructure.db.models  # noqa: F401
from app.core.database import get_session
from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.shared.infrastructure.db.better_auth import BetterAuthUser


from sqlalchemy import event

@pytest.fixture(name="test_engine")
def test_engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(test_engine) -> Iterator[Session]:
    with Session(test_engine) as session:
        # Sembrar usuario BetterAuth de prueba
        user1 = BetterAuthUser(id="user_test_1", name="Usuario Uno", email="uno@test.com")
        user2 = BetterAuthUser(id="user_test_2", name="Usuario Dos", email="dos@test.com")
        session.add(user1)
        session.add(user2)
        session.commit()
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Iterator[TestClient]:
    def get_session_override():
        return session

    test_user = AuthUser(user_id="user_test_1", email="uno@test.com")

    def get_current_user_override():
        return test_user

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_current_user] = get_current_user_override

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
