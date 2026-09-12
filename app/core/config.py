from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = Field(default="API", env="PROJECT_NAME")
    ENVIRONMENT: str = Field(default="DEV", env="ENVIRONMENT")

    # ── Base de datos ─────────────────────────────────────────────────────────
    # Valor por defecto: SQLite local para poder arrancar sin configurar nada.
    # En producción (Render / Railway / Fly.io) o en local contra Neon,
    # define DATABASE_URL en tu .env con la URL completa de PostgreSQL.
    DATABASE_URL: str = Field(default="sqlite:///./dev.db", env="DATABASE_URL")
    SQL_ECHO: bool = Field(default=False, env="SQL_ECHO")

    # ── Módulo Projects ───────────────────────────────────────────────────────
    INVITATION_EXPIRATION_DAYS: int = Field(
        default=3, gt=0, env="INVITATION_EXPIRATION_DAYS"
    )

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    # BETTER_AUTH_SECRET ya NO se usa para verificar JWTs.
    # La verificación cambió de HS256 + secret compartido a EdDSA + JWKS:
    # FastAPI descarga la clave pública desde {FRONTEND_URL}/api/auth/jwks.
    # Se conserva por si algún módulo futuro lo necesita (ej: webhooks propios).
    BETTER_AUTH_SECRET: str = Field(
        default="super-secret-key", env="BETTER_AUTH_SECRET"
    )

    # URL del frontend Next.js. Se usa para construir la URL del JWKS endpoint:
    #   {FRONTEND_URL}/api/auth/jwks
    # En producción: https://tu-dominio.com
    FRONTEND_URL: str = Field(
        default="http://localhost:3000", env="FRONTEND_URL"
    )
    # Limita cuanto espera FastAPI al JWKS de Better Auth durante validacion JWT.
    JWKS_TIMEOUT_SECONDS: float = Field(
        default=5.0, gt=0, env="JWKS_TIMEOUT_SECONDS"
    )

    # Identificador del emisor del JWT (claim "iss").
    # Debe coincidir con JWT_ISSUER configurado en el frontend (lib/auth.ts).
    # Si está vacío, la validación del issuer se desactiva automáticamente.
    JWT_ISSUER: str = Field(default="", env="JWT_ISSUER")

    # Identificador del receptor del JWT (claim "aud").
    # Debe coincidir con JWT_AUDIENCE configurado en el frontend.
    # Si está vacío (recomendado para empezar), la validación se desactiva.
    JWT_AUDIENCE: str = Field(default="", env="JWT_AUDIENCE")

    # ── Better Auth: Configuración de Roles y JWKS ────────────────────────────
    # Si en el frontend tienes instalado el plugin de 'admin', déjalo en True.
    # Si NO usas el plugin de admin en Better Auth, cambia a False en tu .env:
    #   BETTER_AUTH_ENABLE_ROLES=false
    # Al estar en False, el backend NO exige el claim 'role' en el JWT;
    # únicamente valida que el usuario esté autenticado con un token válido.
    BETTER_AUTH_ENABLE_ROLES: bool = Field(
        default=True, env="BETTER_AUTH_ENABLE_ROLES"
    )

    # URL personalizada para descargar el JWKS (útil si FastAPI corre en Docker
    # y debe comunicarse con Next.js mediante red interna como http://frontend:3000/api/auth/jwks
    # mientras el navegador usa http://localhost:3000). Si es None, usa {FRONTEND_URL}/api/auth/jwks.
    BETTER_AUTH_JWKS_URL: str | None = Field(
        default=None, env="BETTER_AUTH_JWKS_URL"
    )

    @property
    def jwks_url(self) -> str:
        """URL definitiva para el JWKS endpoint de Better Auth."""
        if self.BETTER_AUTH_JWKS_URL:
            return self.BETTER_AUTH_JWKS_URL.strip()
        return f"{self.FRONTEND_URL.rstrip('/')}/api/auth/jwks"

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"],
        env="CORS_ORIGINS",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value  # type: ignore[return-value]

    @property
    def database_url_normalized(self) -> str:
        """
        Devuelve la DATABASE_URL lista para SQLAlchemy con el driver correcto.

        Reglas:
        - SQLite  → se mantiene tal cual (usado en DEV por defecto).
        - postgres:// o postgresql:// sin driver explícito
          → se convierte a postgresql+psycopg://  (psycopg v3, el que
            tenemos instalado vía psycopg / psycopg-binary).
        """
        url = self.DATABASE_URL.strip()

        if url.startswith("sqlite"):
            return url

        # Normalizar a psycopg v3
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://"):]
        if url.startswith("postgresql://") and "+psycopg" not in url:
            return "postgresql+psycopg://" + url[len("postgresql://"):]

        return url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url_normalized.startswith("sqlite")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
