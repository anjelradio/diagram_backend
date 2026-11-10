from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
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
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        env="CORS_ORIGINS",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value  # type: ignore[return-value]

    # ── Cloudinary (Almacenamiento de imágenes) ────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = Field(default="", env="CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY: str = Field(default="", env="CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET: str = Field(default="", env="CLOUDINARY_API_SECRET")
    CLOUDINARY_TIMEOUT_SECONDS: int = Field(
        default=30, ge=1, env="CLOUDINARY_TIMEOUT_SECONDS"
    )

    # ── Asistente: Qwen Model Studio ──────────────────────────────────────────
    # La clave puede omitirse en servicios que no ejecutan inferencia; el
    # adaptador valida su presencia al recibir una solicitud del asistente.
    QWEN_API_KEY: SecretStr = Field(default=SecretStr(""), repr=False)
    QWEN_BASE_URL: str = Field(
        default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    QWEN_MODEL_MAIN: str = Field(default="qwen3.7-plus", min_length=1)
    QWEN_MODEL_VISION: str = Field(default="qwen3-vl-plus", min_length=1)
    QWEN_MODEL_PLANNING: str = Field(default="qwen3.7-plus", min_length=1)
    QWEN_MODEL_EXECUTION: str = Field(default="qwen3.8-flash", min_length=1)
    QWEN_MODEL_COMPACTION: str = Field(default="qwen3.8-flash", min_length=1)
    QWEN_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0, le=180)
    QWEN_DEBUG_LOG_CONTENT: bool = Field(default=False)
    AGENT_CONTEXT_MAX_TOKENS: int = Field(default=20_000, ge=8_000, le=100_000)
    AGENT_MEMORY_MAX_TOKENS: int = Field(default=7000, gt=0, le=100_000)
    AGENT_PLANNING_MAX_OUTPUT_TOKENS: int = Field(default=6_000, ge=512, le=32_000)
    AGENT_TASK_MAX_OUTPUT_TOKENS: int = Field(default=2_000, ge=256, le=16_000)
    AGENT_FINAL_MAX_OUTPUT_TOKENS: int = Field(default=700, ge=128, le=4_096)
    AGENT_MAX_PLAN_TASKS: int = Field(default=20, gt=0, le=50)
    AGENT_MAX_DIAGRAM_ACTIONS: int = Field(default=30, gt=0, le=100)
    AGENT_MAX_TOOL_CALLS: int = Field(default=20, gt=0, le=100)
    AGENT_MAX_TOOL_ARGUMENTS_CHARS: int = Field(default=12_000, gt=0, le=100_000)
    AGENT_MAX_TOOL_RESULT_CHARS: int = Field(default=16_000, ge=512, le=100_000)
    AGENT_MAX_ELEMENT_DETAIL_ITEMS: int = Field(default=20, gt=0, le=100)
    AGENT_MAX_EXECUTION_SECONDS: int = Field(default=240, gt=0, le=1800)
    AGENT_PROMPT_VARIANT: str = Field(default="legacy")
    AGENT_DIALOG_MANAGER_ENABLED: bool = Field(default=True)
    AGENT_DIALOG_RECENT_TURNS: int = Field(default=6, ge=1, le=20)
    AGENT_FAST_SYNTHESIS_ENABLED: bool = Field(default=True)

    @field_validator("AGENT_PROMPT_VARIANT")
    @classmethod
    def validate_agent_prompt_variant(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"legacy", "modular"}:
            raise ValueError("AGENT_PROMPT_VARIANT debe ser 'legacy' o 'modular'.")
        return normalized

    @field_validator("QWEN_BASE_URL")
    @classmethod
    def validate_qwen_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        try:
            hostname = parsed.hostname
            _port = parsed.port
        except ValueError as exc:
            raise ValueError("QWEN_BASE_URL debe ser una URL HTTPS válida.") from exc
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("QWEN_BASE_URL debe ser una URL HTTPS válida.")
        return normalized

    @model_validator(mode="after")
    def validate_agent_token_budgets(self):
        if self.AGENT_MEMORY_MAX_TOKENS >= self.AGENT_CONTEXT_MAX_TOKENS:
            raise ValueError(
                "AGENT_MEMORY_MAX_TOKENS debe ser menor que AGENT_CONTEXT_MAX_TOKENS."
            )
        for field_name in (
            "AGENT_PLANNING_MAX_OUTPUT_TOKENS",
            "AGENT_TASK_MAX_OUTPUT_TOKENS",
            "AGENT_FINAL_MAX_OUTPUT_TOKENS",
        ):
            if getattr(self, field_name) >= self.AGENT_CONTEXT_MAX_TOKENS:
                raise ValueError(
                    f"{field_name} debe ser menor que AGENT_CONTEXT_MAX_TOKENS."
                )
        return self

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
