"""
alembic/env.py  ─  Configuración de migraciones para este scaffold.

Cómo funciona:
─────────────
1. Lee DATABASE_URL desde .env (vía core.config.settings).
2. Normaliza automáticamente el driver a psycopg v3.
3. Importa shared.infrastructure.db.models  →  ese módulo es el
   "registry" donde registras todos tus modelos SQLModel.
4. Detecta si la URL es SQLite o PostgreSQL y ajusta los parámetros
   de comparación de tipos y server-defaults en consecuencia.

Para agregar un nuevo modelo al autogenerate:
─────────────────────────────────────────────
    # En app/shared/infrastructure/db/models.py  ← SOLO AHÍ
    from app.modules.users.infrastructure.persistence.models.user_model import UserModel

Después ejecuta:
    alembic revision --autogenerate -m "add users table"
    alembic upgrade head
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

# ── Asegurar que el root del proyecto esté en sys.path ────────────────────────
# Esto permite importar `core`, `shared`, etc. desde cualquier directorio de
# trabajo al correr `alembic` desde la raíz del proyecto.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, pool  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from alembic import context  # noqa: E402

# ── Settings centralizadas (incluyen DATABASE_URL normalizada) ─────────────────
from app.core.config import settings  # noqa: E402

# ── Registry de modelos: IMPORTA AQUÍ TODOS TUS MODELOS SQLModel ──────────────
# Si no importas un modelo, Alembic NO lo detectará en --autogenerate.
import app.shared.infrastructure.db.models  # noqa: F401, E402

# ──────────────────────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Tablas gestionadas por Better Auth (Alembic las ignora) ───────────────────
# Alembic no creará, alterará ni eliminará estas tablas.
# Sin embargo, tus modelos SÍ pueden referenciarlas con ForeignKey.
# Requisito: Better Auth debe haber creado sus tablas ANTES de correr
#            `alembic upgrade head` (ver orden en el Release Command).
BETTER_AUTH_TABLES: frozenset[str] = frozenset({
    "user",
    "account",
    "session",
    "verification",
    "jwks",
})


def include_object(object, name, type_, reflected, compare_to):  # noqa: A002
    """
    Filtro de Alembic: devuelve False para los objetos que NO deben
    ser gestionados por nuestras migraciones.

    - Excluye las tablas de Better Auth (ya existen, Better Auth las gestiona).
    - El resto de tablas y columnas sí se incluyen en el autogenerate.
    """
    if type_ == "table" and name in BETTER_AUTH_TABLES:
        return False
    return True

target_metadata = SQLModel.metadata

DATABASE_URL: str = settings.database_url_normalized


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """
    Modo offline: genera el SQL sin necesitar conexión real a la DB.
    Útil para revisar qué cambiaría antes de aplicarlo, o para
    generar scripts SQL para correr manualmente en producción.

    Ejecutar con:  alembic upgrade head --sql
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=not _is_sqlite(DATABASE_URL),
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(DATABASE_URL),
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Modo online (normal): conecta a la DB y aplica las migraciones.

    Usa NullPool para evitar conexiones colgadas — ideal para scripts
    CLI/CI.  La app en sí usa su propio pool configurado en database.py.
    """
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        is_sq = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=not is_sq,
            render_as_batch=is_sq,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
