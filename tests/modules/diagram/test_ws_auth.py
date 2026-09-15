import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketException, status
from sqlmodel import Session

from app.core.security.auth import AuthUser
from app.modules.diagram.infrastructure.api.dependencies.ws_auth import (
    get_ws_auth_user,
    get_ws_project_access,
)
from app.modules.projects.domain.enums.project_access_role import ProjectAccessRole
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_get_ws_auth_user_missing_token() -> None:
    ws = MagicMock(spec=WebSocket)
    ws.query_params = {}
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_auth_user(ws)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_get_ws_auth_user_invalid_token() -> None:
    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"token": "invalid.jwt.token"}
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_auth_user(ws)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_get_ws_auth_user_valid_token_with_name() -> None:
    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"token": "valid-token"}

    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = "public_key"
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

    mock_payload = {
        "sub": "user_123",
        "email": "user@example.com",
        "name": "Alice Dev",
        "role": "admin",
    }

    with patch("app.modules.diagram.infrastructure.api.dependencies.ws_auth._get_jwks_client", return_value=mock_jwk_client):
        with patch("jwt.decode", return_value=mock_payload):
            auth_user = get_ws_auth_user(ws)
            assert auth_user.user_id == "user_123"
            assert auth_user.email == "user@example.com"
            assert auth_user.name == "Alice Dev"


def test_get_ws_auth_user_fallback_name_to_user_id_never_email() -> None:
    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"token": "valid-token"}

    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = "public_key"
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

    # Caso 1: name no presente
    mock_payload_no_name = {
        "sub": "user_456",
        "email": "sensitive@example.com",
        "role": "user",
    }

    with patch("app.modules.diagram.infrastructure.api.dependencies.ws_auth._get_jwks_client", return_value=mock_jwk_client):
        with patch("jwt.decode", return_value=mock_payload_no_name):
            auth_user = get_ws_auth_user(ws)
            assert auth_user.user_id == "user_456"
            assert auth_user.name == "user_456"
            assert auth_user.name != auth_user.email

    # Caso 2: name vacío o espacios
    mock_payload_empty_name = {
        "sub": "user_789",
        "email": "sensitive2@example.com",
        "name": "   ",
        "role": "user",
    }

    with patch("app.modules.diagram.infrastructure.api.dependencies.ws_auth._get_jwks_client", return_value=mock_jwk_client):
        with patch("jwt.decode", return_value=mock_payload_empty_name):
            auth_user = get_ws_auth_user(ws)
            assert auth_user.user_id == "user_789"
            assert auth_user.name == "user_789"
            assert auth_user.name != auth_user.email


def test_get_ws_project_access_owner(session: Session, test_project: ProjectModel, owner_user: AuthUser) -> None:
    context = get_ws_project_access(session, test_project.id, owner_user)
    assert context.access_role == ProjectAccessRole.OWNER
    assert context.project.id == test_project.id


def test_get_ws_project_access_editor(session: Session, test_project: ProjectModel, editor_user: AuthUser) -> None:
    context = get_ws_project_access(session, test_project.id, editor_user)
    assert context.access_role == ProjectAccessRole.EDITOR
    assert context.project.id == test_project.id


def test_get_ws_project_access_reader(session: Session, test_project: ProjectModel, reader_user: AuthUser) -> None:
    context = get_ws_project_access(session, test_project.id, reader_user)
    assert context.access_role == ProjectAccessRole.READER
    assert context.project.id == test_project.id


def test_get_ws_project_access_removed_user_rejected(session: Session, test_project: ProjectModel, removed_user: AuthUser) -> None:
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_project_access(session, test_project.id, removed_user)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_get_ws_project_access_banned_user_rejected(session: Session, test_project: ProjectModel, banned_user: AuthUser) -> None:
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_project_access(session, test_project.id, banned_user)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_get_ws_project_access_stranger_user_rejected(session: Session, test_project: ProjectModel, stranger_user: AuthUser) -> None:
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_project_access(session, test_project.id, stranger_user)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_get_ws_project_access_nonexistent_project_rejected(session: Session, owner_user: AuthUser) -> None:
    with pytest.raises(WebSocketException) as exc_info:
        get_ws_project_access(session, uuid.uuid4(), owner_user)
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
