"""Autenticación JWT de Better Auth para los endpoints de FastAPI.

Better Auth mantiene la sesión del navegador mediante cookie httpOnly y emite
JWT cortos EdDSA para servicios externos. El frontend envía esos JWT en
``Authorization: Bearer <token>`` y esta API verifica su firma mediante:

    GET {FRONTEND_URL}/api/auth/jwks (o BETTER_AUTH_JWKS_URL)

El backend soporta dos modos de operación mediante BETTER_AUTH_ENABLE_ROLES:
- True  (default): El token debe incluir el claim 'role'.
- False: No se exigen roles; CurrentUser solo verifica que el usuario esté autenticado.
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.config import settings
from app.core.errors.exceptions import APIHTTPException

# ── Esquema Bearer ────────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


# ── Cliente JWKS ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _get_jwks_client() -> PyJWKClient:
    """
    Crea el cliente JWKS una sola vez (singleton via lru_cache).

    PyJWKClient descarga las claves públicas cuando llega el primer JWT que
    necesita validación y después las cachea en memoria.

    Usa settings.jwks_url ({FRONTEND_URL}/api/auth/jwks o BETTER_AUTH_JWKS_URL).
    """
    return PyJWKClient(
        settings.jwks_url,
        cache_keys=True,
        headers={"Accept": "application/json"},
        timeout=settings.JWKS_TIMEOUT_SECONDS,
    )


# ── Roles ─────────────────────────────────────────────────────────────────────
class Role(StrEnum):
    """
    Roles disponibles en el sistema (cuando BETTER_AUTH_ENABLE_ROLES=True).

    El valor debe coincidir EXACTAMENTE con el claim "role" del JWT,
    que a su vez viene del plugin 'admin' de Better Auth.

    Agrega los roles que necesites para tu proyecto. Ejemplo:
        EDITOR = "editor"
        MODERATOR = "moderator"
    """

    ADMIN = "admin"
    USER = "user"


# ── DTO del usuario autenticado ───────────────────────────────────────────────
@dataclass(frozen=True)
class AuthUser:
    """
    Representa al usuario cuya identidad fue verificada con el JWT.
    Inmutable por diseño (frozen=True).

    Campos:
        user_id → claim "sub" del JWT (ID del usuario en Better Auth)
        email   → claim "email" del JWT
        name    → claim "name" del JWT
        role    → claim "role" del JWT (None si BETTER_AUTH_ENABLE_ROLES=False)
    """

    user_id: str
    email: str
    name: str = ""
    role: Role | str | None = None

    def has_role(self, *roles: Role | str) -> bool:
        """True si el usuario tiene alguno de los roles dados."""
        if self.role is None:
            return False
        role_vals = [r.value if isinstance(r, Role) else str(r) for r in roles]
        current_val = self.role.value if isinstance(self.role, Role) else str(self.role)
        return current_val in role_vals


# ── Dependencia base: decodifica y valida el JWT ──────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """
    Dependencia FastAPI que extrae y valida el JWT del header:
        Authorization: Bearer <token>

    Algoritmo: EdDSA (Ed25519) — el default de Better Auth.
    La firma se verifica con la clave pública del JWKS endpoint.

    Comportamiento de roles (BETTER_AUTH_ENABLE_ROLES):
    - True (default): Exige que el JWT contenga un claim 'role' válido.
    - False: No exige roles; solo valida que el usuario esté autenticado.

    Lanza:
        401 - token ausente, expirado o inválido.
        403 - token válido sin el rol requerido (si roles están activos).
        503 - JWKS de Better Auth no disponible.
    """
    if credentials is None:
        raise APIHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_MISSING",
            message="No se proporcionó token de autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(credentials.credentials)

        payload = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["EdDSA"],
            options={
                "require": ["exp", "sub"],
                "verify_exp": True,
                "verify_aud": bool(settings.JWT_AUDIENCE),
            },
            audience=settings.JWT_AUDIENCE or None,
            issuer=settings.JWT_ISSUER or None,
        )

    except jwt.ExpiredSignatureError:
        raise APIHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_EXPIRED",
            message="El token ha expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except PyJWKClientConnectionError:
        raise APIHTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_PROVIDER_UNAVAILABLE",
            message="El proveedor de autenticación no está disponible.",
        )
    except (PyJWKClientError, jwt.InvalidTokenError):
        raise APIHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_INVALID",
            message="El token es inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    email = payload.get("email")
    name = payload.get("name")

    if not isinstance(user_id, str) or not user_id:
        raise APIHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_INVALID",
            message="El token no contiene una identidad válida.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Resolución de rol según configuración ─────────────────────────────────
    role: Role | str | None = None
    if settings.BETTER_AUTH_ENABLE_ROLES:
        raw_role = payload.get("role")
        if not raw_role:
            raise APIHTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTH_ROLE_MISSING",
                message="El token no contiene un rol (BETTER_AUTH_ENABLE_ROLES=True).",
            )
        try:
            role = Role(raw_role)
        except (TypeError, ValueError):
            raise APIHTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTH_FORBIDDEN",
                message="No tienes permisos para acceder a este recurso.",
            )

    return AuthUser(
        user_id=user_id,
        email=email if isinstance(email, str) else "",
        name=name if isinstance(name, str) and name.strip() else user_id,
        role=role,
    )


# ── Guard de roles ────────────────────────────────────────────────────────────
def require_role(*roles: Role | str):
    """
    Factory que devuelve una dependencia FastAPI que exige uno o más roles.

    Uso:
        AdminOnly = Annotated[AuthUser, Depends(require_role(Role.ADMIN))]
        Staff = Annotated[AuthUser, Depends(require_role(Role.ADMIN, "editor"))]

    Nota: si BETTER_AUTH_ENABLE_ROLES=False, este guard lanzará 403
    indicando que los roles no están habilitados.
    """

    def _guard(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if not settings.BETTER_AUTH_ENABLE_ROLES:
            raise APIHTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTH_ROLES_DISABLED",
                message="El sistema de roles no está habilitado en este backend (BETTER_AUTH_ENABLE_ROLES=False).",
            )

        if not user.has_role(*roles):
            raise APIHTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTH_FORBIDDEN",
                message="No tienes permisos para acceder a este recurso.",
            )
        return user

    return _guard


# ── Aliases listos para usar en endpoints ─────────────────────────────────────
CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
"""Cualquier usuario con JWT válido (funciona tanto con roles como sin roles)."""

Admin = Annotated[AuthUser, Depends(require_role(Role.ADMIN))]
"""Solo usuarios con role='admin' (requiere BETTER_AUTH_ENABLE_ROLES=True)."""
