from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
import app.shared.infrastructure.db.models  # noqa: F401

# ── Argumentos condicionales según el motor ───────────────────────────────────
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
pool_pre_ping = not settings.is_sqlite  # ping preventivo solo en PostgreSQL

from sqlalchemy import event

engine = create_engine(
    settings.database_url_normalized,
    echo=settings.SQL_ECHO,
    connect_args=connect_args,
    pool_pre_ping=pool_pre_ping,
    pool_recycle=300,
)

if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()



def init_db() -> None:
    """
    Crea las tablas definidas en SQLModel.metadata.

    ⚠️  Úsalo SOLO en DEV cuando no quieras gestionar migraciones.
    En PROD (o cuando uses Alembic), este método no se llama —
    las tablas las crea/actualiza `alembic upgrade head`.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """Dependencia FastAPI que provee una sesión de BD por request."""
    with Session(engine) as session:
        yield session
