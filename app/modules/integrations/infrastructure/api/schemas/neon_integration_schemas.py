from __future__ import annotations

from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ConfigureNeonIntegrationRequest(BaseModel):
    """Payload para configurar la API Key de Neon."""

    api_key: str = Field(..., min_length=1, description="API Key de Neon (napi_...)")


class NeonIntegrationStatusRead(BaseModel):
    """Esquema de respuesta para el estado de la integración de Neon."""

    project_id: UUID
    provider: str
    has_api_key: bool
    is_initialized: bool
    neon_project_id: str | None = None
    neon_database_name: str | None = None
    neon_console_url: str | None = None
    neon_branch_id: str | None = None
    last_synced_at: str | None = None


class NeonSyncResultRead(BaseModel):
    """Esquema de respuesta para el resultado de sincronización en Neon."""

    has_changes: bool
    created_tables: list[str] = Field(default_factory=list)
    dropped_tables: list[str] = Field(default_factory=list)
    added_columns: dict[str, list[str]] = Field(default_factory=dict)
    dropped_columns: dict[str, list[str]] = Field(default_factory=dict)
    altered_columns: dict[str, list[str]] = Field(default_factory=dict)
    added_foreign_keys: list[str] = Field(default_factory=list)
    dropped_foreign_keys: list[str] = Field(default_factory=list)
