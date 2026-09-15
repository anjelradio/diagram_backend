"""Autenticación y autorización del canal WebSocket."""

from uuid import UUID

import jwt
from fastapi import WebSocket, WebSocketException, status
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.security.auth import AuthUser, _get_jwks_client
from app.modules.projects.application.services.project_access_policy import (
    ProjectAccessContext,
    ProjectAccessPolicy,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from sqlmodel import Session


def get_ws_auth_user(websocket: WebSocket) -> AuthUser:
    """Valida el JWT enviado como query param sin revelar el motivo del rechazo."""
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["EdDSA"],
            options={
                "require": ["exp", "sub"],
                "verify_exp": True,
            },
        )
    except (jwt.InvalidTokenError, PyJWKClientError, PyJWKClientConnectionError):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    name = payload.get("name")
    return AuthUser(
        user_id=user_id,
        email=payload.get("email") if isinstance(payload.get("email"), str) else "",
        name=name if isinstance(name, str) and name.strip() else user_id,
        role=payload.get("role") if isinstance(payload.get("role"), str) else None,
    )


def get_ws_project_access(
    db: Session,
    project_id: UUID,
    user: AuthUser,
) -> ProjectAccessContext:
    """Resuelve acceso con la misma política REST; todos los fallos son 1008."""
    policy = ProjectAccessPolicy(
        project_repository=SQLModelProjectRepository(db),
        project_member_repository=SQLModelProjectMemberRepository(db),
    )
    try:
        return policy.resolve_access(project_id, user.user_id)
    except Exception as exc:
        # No se revela si el proyecto existe ni el motivo de la denegación.
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION) from exc
