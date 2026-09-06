from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.domain.exceptions import (
    ConflictException,
    DomainException,
    NotFoundException,
    ValidationException,
)


def format_error(code: str, message: str) -> dict[str, dict[str, str]]:
    """Formato universal para las respuestas de error."""
    return {"error": {"code": code, "message": message}}


def setup_exception_handlers(app: FastAPI) -> None:
    # ── 1. Errores de Dominio ─────────────────────────────────────────────────

    @app.exception_handler(NotFoundException)
    async def not_found_handler(request: Request, exc: NotFoundException):
        return JSONResponse(status_code=404, content=format_error(exc.code, exc.message))

    @app.exception_handler(ConflictException)
    async def conflict_handler(request: Request, exc: ConflictException):
        return JSONResponse(status_code=409, content=format_error(exc.code, exc.message))

    @app.exception_handler(ValidationException)
    async def validation_handler(request: Request, exc: ValidationException):
        return JSONResponse(status_code=400, content=format_error(exc.code, exc.message))

    @app.exception_handler(DomainException)
    async def domain_generic_handler(request: Request, exc: DomainException):
        return JSONResponse(status_code=400, content=format_error(exc.code, exc.message))

    # ── 2. Errores de Pydantic / Validación de Request ────────────────────────

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        error = exc.errors()[0]
        campo = ".".join(str(loc) for loc in error["loc"])
        mensaje = f"Error en '{campo}': {error['msg']}"

        return JSONResponse(
            status_code=422,
            content=format_error("SCHEMA_VALIDATION_ERROR", mensaje),
        )

    # ── 3. Errores Genéricos HTTP (ej. 401, 403 o rutas 404 no definidas) ─────

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=format_error(
                getattr(exc, "code", f"HTTP_ERROR_{exc.status_code}"),
                str(exc.detail),
            ),
            headers=exc.headers,
        )

    # ── 4. Paracaídas Final (Errores 500 no capturados) ───────────────────────

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        import logging
        logging.getLogger(__name__).error("Unhandled exception", exc_info=exc)

        return JSONResponse(
            status_code=500,
            content=format_error("INTERNAL_SERVER_ERROR", "Ha ocurrido un error interno del servidor."),
        )
