from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NeonInvalidCredentialsException,
    NeonProjectAlreadyInitializedException,
    NotionInvalidCredentialsException,
    NotionProjectAlreadyInitializedException,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ProjectIntegration:
    """Entidad de dominio que representa la integración de un proyecto con un proveedor externo (Notion, Neon)."""

    id: UUID
    project_id: UUID
    provider: IntegrationProvider
    encrypted_api_key: str
    external_page_id: str | None = None
    external_database_id: str | None = None
    config_json: dict[str, Any] = field(default_factory=dict)
    created_date: datetime = field(default_factory=_utc_now)
    modified_date: datetime = field(default_factory=_utc_now)
    is_active: bool = True

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        provider: IntegrationProvider,
        encrypted_api_key: str,
        parent_page_id: str | None = None,
        workspace_name: str | None = None,
    ) -> ProjectIntegration:
        if not encrypted_api_key or not encrypted_api_key.strip():
            if provider == IntegrationProvider.NEON:
                raise NeonInvalidCredentialsException("La API Key encriptada de Neon no puede estar vacía.")
            raise NotionInvalidCredentialsException("La API Key encriptada no puede estar vacía.")
        config: dict[str, Any] = {}
        if parent_page_id and parent_page_id.strip():
            config["parent_page_id"] = parent_page_id.strip()
        if workspace_name and workspace_name.strip():
            config["workspace_name"] = workspace_name.strip()
        now = _utc_now()
        return cls(
            id=uuid4(),
            project_id=project_id,
            provider=provider,
            encrypted_api_key=encrypted_api_key.strip(),
            external_page_id=None,
            external_database_id=None,
            config_json=config,
            created_date=now,
            modified_date=now,
            is_active=True,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        provider: IntegrationProvider,
        encrypted_api_key: str,
        external_page_id: str | None,
        external_database_id: str | None,
        config_json: dict[str, Any] | None,
        created_date: datetime,
        modified_date: datetime,
        is_active: bool = True,
    ) -> ProjectIntegration:
        return cls(
            id=id,
            project_id=project_id,
            provider=provider,
            encrypted_api_key=encrypted_api_key,
            external_page_id=external_page_id,
            external_database_id=external_database_id,
            config_json=dict(config_json or {}),
            created_date=created_date,
            modified_date=modified_date,
            is_active=is_active,
        )

    @property
    def is_initialized(self) -> bool:
        """Indica si el proyecto ya fue inicializado en el proveedor externo (ej. página y BD creadas en Notion)."""
        return bool(
            self.external_page_id
            and self.external_page_id.strip()
            and self.external_database_id
            and self.external_database_id.strip()
        )

    @property
    def notion_page_url(self) -> str | None:
        url = self.config_json.get("notion_page_url")
        return str(url) if isinstance(url, str) and url.strip() else None

    @property
    def parent_page_id(self) -> str | None:
        parent = self.config_json.get("parent_page_id")
        return str(parent) if isinstance(parent, str) and parent.strip() else None

    def update_credentials(
        self,
        *,
        encrypted_api_key: str,
        parent_page_id: str | None = None,
        workspace_name: str | None = None,
    ) -> None:
        if not encrypted_api_key or not encrypted_api_key.strip():
            if provider == IntegrationProvider.NEON:
                raise NeonInvalidCredentialsException("La API Key encriptada de Neon no puede estar vacía.")
            raise NotionInvalidCredentialsException("La API Key encriptada no puede estar vacía.")
        self.encrypted_api_key = encrypted_api_key.strip()
        updated_config = dict(self.config_json)
        if parent_page_id is not None:
            if parent_page_id.strip():
                updated_config["parent_page_id"] = parent_page_id.strip()
            else:
                updated_config.pop("parent_page_id", None)
        if workspace_name and workspace_name.strip():
            updated_config["workspace_name"] = workspace_name.strip()
        self.config_json = updated_config
        self.modified_date = _utc_now()

    def ensure_can_initialize(self) -> None:
        """Verifica que el proyecto no haya sido inicializado previamente."""
        if self.is_initialized:
            if self.provider == IntegrationProvider.NEON:
                raise NeonProjectAlreadyInitializedException()
            raise NotionProjectAlreadyInitializedException()

    @property
    def neon_project_id(self) -> str | None:
        return self.external_page_id if self.provider == IntegrationProvider.NEON else None

    @property
    def neon_database_name(self) -> str | None:
        return self.external_database_id if self.provider == IntegrationProvider.NEON else None

    @property
    def neon_branch_id(self) -> str | None:
        val = self.config_json.get("neon_branch_id")
        return str(val) if isinstance(val, str) and val.strip() else None

    @property
    def neon_console_url(self) -> str | None:
        val = self.config_json.get("neon_console_url")
        return str(val) if isinstance(val, str) and val.strip() else None

    @property
    def encrypted_connection_uri(self) -> str | None:
        val = self.config_json.get("encrypted_connection_uri")
        return str(val) if isinstance(val, str) and val.strip() else None

    @property
    def last_synced_at(self) -> str | None:
        val = self.config_json.get("last_synced_at")
        return str(val) if isinstance(val, str) and val.strip() else None

    def mark_notion_initialized(
        self,
        *,
        page_id: str,
        database_id: str,
        page_url: str | None = None,
        initial_description: str | None = None,
    ) -> None:
        """Registra la página raíz y la base de datos de tareas creadas en Notion (solo permitido una vez)."""
        self.ensure_can_initialize()
        if not page_id or not page_id.strip() or not database_id or not database_id.strip():
            raise ValueError("page_id y database_id son obligatorios al inicializar Notion.")
        self.external_page_id = page_id.strip()
        self.external_database_id = database_id.strip()
        updated_config = dict(self.config_json)
        if page_url and page_url.strip():
            updated_config["notion_page_url"] = page_url.strip()
        if initial_description and initial_description.strip():
            updated_config["initial_description"] = initial_description.strip()
        updated_config["initialized_at"] = _utc_now().isoformat()
        self.config_json = updated_config
        self.modified_date = _utc_now()

    def mark_neon_initialized(
        self,
        *,
        neon_project_id: str,
        database_name: str,
        branch_id: str | None = None,
        console_url: str | None = None,
        encrypted_connection_uri: str | None = None,
    ) -> None:
        """Registra el proyecto y base de datos inicializados en Neon."""
        self.ensure_can_initialize()
        if not neon_project_id or not neon_project_id.strip() or not database_name or not database_name.strip():
            raise ValueError("neon_project_id y database_name son obligatorios al inicializar Neon.")
        self.external_page_id = neon_project_id.strip()
        self.external_database_id = database_name.strip()
        updated_config = dict(self.config_json)
        if branch_id and branch_id.strip():
            updated_config["neon_branch_id"] = branch_id.strip()
        if console_url and console_url.strip():
            updated_config["neon_console_url"] = console_url.strip()
        if encrypted_connection_uri and encrypted_connection_uri.strip():
            updated_config["encrypted_connection_uri"] = encrypted_connection_uri.strip()
        updated_config["initialized_at"] = _utc_now().isoformat()
        self.config_json = updated_config
        self.modified_date = _utc_now()

    def record_neon_sync(self, *, summary: dict[str, Any] | None = None) -> None:
        """Registra una sincronización exitosa contra Neon."""
        updated_config = dict(self.config_json)
        updated_config["last_synced_at"] = _utc_now().isoformat()
        if summary is not None:
            updated_config["last_sync_summary"] = summary
        self.config_json = updated_config
        self.modified_date = _utc_now()
