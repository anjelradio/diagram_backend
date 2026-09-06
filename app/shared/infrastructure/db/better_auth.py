"""
Tablas fantasma de Better Auth.
────────────────────────────────
Estas clases le dicen a SQLAlchemy (y por tanto a Alembic) que las
tablas de Better Auth EXISTEN en la base de datos, sin que Alembic
las gestione.

Sirven para poder definir ForeignKeys hacia ellas desde tus propios
modelos con type-safety completo, evitando strings mágicos como
Field(foreign_key="user.id").

IMPORTANTE:
- Alembic las ignora gracias al filtro `include_object` en env.py.
- Better Auth debe haber creado sus tablas antes de correr
  `alembic upgrade head`.
- NO importes estas clases en models.py (el registry de Alembic).
  Solo úsalas como referencia de tipo en tus propios modelos.

Uso en un modelo tuyo:
───────────────────────
    from app.shared.infrastructure.db.better_auth import BetterAuthUser

    class Profile(BaseModel, table=True):
        user_id: str = Field(foreign_key="user.id", unique=True)
"""

from sqlmodel import Field, SQLModel


class BetterAuthUser(SQLModel, table=True):
    """
    Reflejo de la tabla `user` que genera Better Auth.
    Solo para referencias de tipo — Alembic no la gestiona.
    Los campos dependientes de plugins (role, banned, banReason, etc.)
    se marcan como opcionales para ser compatibles con cualquier configuración.
    """

    __tablename__ = "user"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    name: str
    email: str
    emailVerified: bool = Field(default=False)
    image: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    role: str | None = None
    banned: bool | None = None
    banReason: str | None = None
    banExpires: str | None = None
