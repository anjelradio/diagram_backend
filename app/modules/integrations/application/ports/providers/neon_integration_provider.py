from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresSchema,
)


@dataclass(frozen=True, slots=True)
class NeonProvisionedProject:
    """Resultado del aprovisionamiento de un proyecto y base de datos en Neon."""

    project_id: str
    database_name: str
    branch_id: str
    console_url: str
    connection_uri: str


class NeonIntegrationProvider(ABC):
    """Puerto para interactuar con la API / MCP oficial de Neon Serverless PostgreSQL."""

    @abstractmethod
    def validate_api_key(self, api_key: str) -> tuple[bool, str | None]:
        """Valida la API key contra la API de Neon. Retorna (es_valido, error_o_usuario)."""

    @abstractmethod
    def create_project_and_database(
        self,
        api_key: str,
        project_name: str,
    ) -> NeonProvisionedProject:
        """Crea un proyecto dedicado en Neon y retorna los identificadores y URI de conexión."""

    @abstractmethod
    def introspect_database_schema(
        self,
        connection_uri: str,
    ) -> CurrentPostgresSchema:
        """Inspecciona information_schema en la base de datos de Neon y retorna el esquema actual."""

    @abstractmethod
    def execute_sql_migration(
        self,
        connection_uri: str,
        statements: list[str],
    ) -> bool:
        """Ejecuta una lista de sentencias DDL dentro de un bloque transaccional."""
