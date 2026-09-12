# app/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, init_db
from app.core.dependencies import get_event_bus
from app.core.errors.handlers import setup_exception_handlers
from app.core.events.subscriptions import configure_event_subscriptions

# Configuración de logging estándar
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from app.modules.projects.infrastructure.api.routers.project_members_router import (
    router as project_members_router,
)
from app.modules.projects.infrastructure.api.routers.projects_router import (
    router as projects_router,
)


# ==============================================================================
# LIFESPAN
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación.

    - DEV  + SQLite   → crea tablas automáticamente (rápido para prototipar).
    - DEV  + Postgres → se asume que Alembic ya corrió (`alembic upgrade head`).
    - PROD            → Alembic siempre. init_db() nunca se llama.
    """
    if settings.ENVIRONMENT == "DEV" and settings.is_sqlite:
        logger.info("DEV + SQLite — inicializando tablas con SQLModel...")
        init_db()
    else:
        logger.info(
            "Modo %s con %s — las migraciones deben ejecutarse con Alembic.",
            settings.ENVIRONMENT,
            "SQLite" if settings.is_sqlite else "PostgreSQL",
        )

    # ── Event Bus — registrar suscripciones de handlers ────────────────────
    configure_event_subscriptions(get_event_bus())
    logger.info("Event Bus configurado con suscripciones del sistema.")

    yield


# ==============================================================================
# APP FASTAPI
# ==============================================================================
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,  # Mantiene el token JWT al recargar Swagger
    },
)

setup_exception_handlers(app)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# RUTAS GENÉRICAS / HEALTHCHECK
# ==============================================================================
@app.get("/health", tags=["System"], summary="Verificar estado del sistema y BD")
def health_check():
    """
    Comprueba el estado de la API y la conectividad real con la base de datos.
    Devuelve 200 si todo está saludable, o 503 si la BD no responde.
    """
    db_status = "connected"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Healthcheck: fallo al conectar con la base de datos: %s", exc)
        db_status = "unreachable"

    payload = {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": {
            "engine": "SQLite" if settings.is_sqlite else "PostgreSQL",
            "status": db_status,
        },
        "environment": settings.ENVIRONMENT,
    }

    if db_status != "connected":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    return payload


# ==============================================================================
# REGISTRO DE ROUTERS
# ==============================================================================
app.include_router(projects_router, prefix="/api")
app.include_router(project_members_router, prefix="/api")
