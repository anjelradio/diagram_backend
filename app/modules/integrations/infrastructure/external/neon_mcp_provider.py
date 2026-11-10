from __future__ import annotations

import logging
from typing import Any
import httpx
import psycopg

from app.modules.integrations.application.ports.providers.neon_integration_provider import (
    NeonIntegrationProvider,
    NeonProvisionedProject,
)
from app.modules.integrations.application.services.postgres_schema_diff_service import (
    CurrentPostgresColumn,
    CurrentPostgresForeignKey,
    CurrentPostgresSchema,
    CurrentPostgresTable,
)
from app.modules.integrations.domain.exceptions import (
    NeonInvalidCredentialsException,
    NeonMigrationExecutionException,
)

logger = logging.getLogger(__name__)

NEON_API_BASE_URL = "https://console.neon.tech/api/v2"


class NeonMcpProvider(NeonIntegrationProvider):
    """Implementación oficial del proveedor de integración con Neon PostgreSQL Serverless."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def validate_api_key(self, api_key: str) -> tuple[bool, str | None]:
        clean_key = (api_key or "").strip()
        if not clean_key:
            return False, "La API key no puede estar vacía."

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                # Validar credencial listando proyectos con límite 1 en Neon API v2
                resp = client.get(
                    f"{NEON_API_BASE_URL}/projects?limit=1",
                    headers=self._headers(clean_key),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    projects = data.get("projects") or []
                    account_label = "Neon Account"
                    if projects and isinstance(projects, list) and len(projects) > 0:
                        first_name = projects[0].get("name")
                        if first_name:
                            account_label = f"Neon ({first_name})"
                    return True, account_label
                if resp.status_code in (401, 403):
                    return False, "API Key de Neon no autorizada o expirada. Verifica que la clave sea correcta."

                # Fallback secundario contra /api_keys
                resp_keys = client.get(
                    f"{NEON_API_BASE_URL}/api_keys",
                    headers=self._headers(clean_key),
                )
                if resp_keys.status_code == 200:
                    return True, "Neon User"
                if resp_keys.status_code in (401, 403):
                    return False, "API Key de Neon no autorizada o expirada. Verifica que la clave sea correcta."

                return False, f"Error al verificar API Key en Neon: HTTP {resp.status_code}"
        except Exception as exc:
            logger.warning("Error de conexión al validar API key de Neon: %s", exc)
            return False, f"No se pudo conectar con la API de Neon: {str(exc)}"

    def create_project_and_database(
        self,
        api_key: str,
        project_name: str,
    ) -> NeonProvisionedProject:
        clean_key = (api_key or "").strip()
        is_valid, err_msg = self.validate_api_key(clean_key)
        if not is_valid:
            raise NeonInvalidCredentialsException(err_msg or "API Key de Neon inválida.")

        safe_project_name = project_name.strip()[:64] or "UML Diagram Project"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                payload = {
                    "project": {
                        "name": safe_project_name,
                    }
                }
                resp = client.post(
                    f"{NEON_API_BASE_URL}/projects",
                    headers=self._headers(clean_key),
                    json=payload,
                )
                if resp.status_code not in (200, 201):
                    raise NeonMigrationExecutionException(
                        f"Neon API rechazó la creación del proyecto: HTTP {resp.status_code} - {resp.text}"
                    )

                data = resp.json()
                proj_data = data.get("project", {})
                project_id = proj_data.get("id")
                if not project_id:
                    raise NeonMigrationExecutionException("Neon no devolvió un project_id válido.")

                # Extraer connection string
                conn_uris = data.get("connection_uris", [])
                connection_uri = ""
                if conn_uris and isinstance(conn_uris, list) and "connection_uri" in conn_uris[0]:
                    connection_uri = conn_uris[0]["connection_uri"]

                # Extraer base de datos
                databases = data.get("databases", [])
                db_name = "neondb"
                if databases and isinstance(databases, list) and "name" in databases[0]:
                    db_name = databases[0]["name"]

                # Extraer branch principal
                branches = data.get("branches", [])
                branch_id = ""
                if branches and isinstance(branches, list) and "id" in branches[0]:
                    branch_id = branches[0]["id"]

                console_url = f"https://console.neon.tech/app/projects/{project_id}"

                return NeonProvisionedProject(
                    project_id=project_id,
                    database_name=db_name,
                    branch_id=branch_id,
                    console_url=console_url,
                    connection_uri=connection_uri,
                )
        except NeonInvalidCredentialsException:
            raise
        except Exception as exc:
            logger.exception("Error al crear proyecto en Neon: %s", exc)
            raise NeonMigrationExecutionException(f"Error al aprovisionar proyecto en Neon: {str(exc)}") from exc

    def introspect_database_schema(
        self,
        connection_uri: str,
    ) -> CurrentPostgresSchema:
        if not connection_uri:
            return CurrentPostgresSchema(tables={})

        tables: dict[str, CurrentPostgresTable] = {}

        try:
            with psycopg.connect(connection_uri, autocommit=True, connect_timeout=15) as conn:
                with conn.cursor() as cur:
                    # 1. Obtener tablas de public
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
                    )
                    table_names = [row[0] for row in cur.fetchall()]

                    # 2. Obtener columnas
                    cur.execute(
                        "SELECT table_name, column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "ORDER BY table_name, ordinal_position;"
                    )
                    columns_by_table: dict[str, dict[str, CurrentPostgresColumn]] = {}
                    for tbl, col, dt, is_null, default_val in cur.fetchall():
                        col_record = CurrentPostgresColumn(
                            name=col,
                            data_type=dt,
                            is_nullable=(str(is_null).upper() == "YES"),
                            is_primary_key=False,
                            default_value=default_val,
                        )
                        columns_by_table.setdefault(tbl, {})[col] = col_record

                    # 3. Obtener Primary Keys
                    cur.execute(
                        "SELECT tc.table_name, kcu.column_name "
                        "FROM information_schema.table_constraints tc "
                        "JOIN information_schema.key_column_usage kcu "
                        "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                        "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY';"
                    )
                    pks_by_table: dict[str, list[str]] = {}
                    for tbl, col in cur.fetchall():
                        pks_by_table.setdefault(tbl, []).append(col)
                        if tbl in columns_by_table and col in columns_by_table[tbl]:
                            prev = columns_by_table[tbl][col]
                            columns_by_table[tbl][col] = CurrentPostgresColumn(
                                name=prev.name,
                                data_type=prev.data_type,
                                is_nullable=prev.is_nullable,
                                is_primary_key=True,
                                default_value=prev.default_value,
                            )

                    # 4. Obtener Foreign Keys
                    cur.execute(
                        "SELECT tc.table_name, tc.constraint_name, kcu.column_name, "
                        "       ccu.table_name AS foreign_table_name, ccu.column_name AS foreign_column_name "
                        "FROM information_schema.table_constraints tc "
                        "JOIN information_schema.key_column_usage kcu "
                        "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                        "JOIN information_schema.constraint_column_usage ccu "
                        "  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
                        "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'FOREIGN KEY';"
                    )
                    fks_by_table: dict[str, dict[str, CurrentPostgresForeignKey]] = {}
                    for tbl, c_name, col, f_tbl, f_col in cur.fetchall():
                        fk_record = CurrentPostgresForeignKey(
                            constraint_name=c_name,
                            column_name=col,
                            foreign_table_name=f_tbl,
                            foreign_column_name=f_col,
                        )
                        fks_by_table.setdefault(tbl, {})[c_name] = fk_record

                    for tbl in table_names:
                        tables[tbl] = CurrentPostgresTable(
                            name=tbl,
                            columns=columns_by_table.get(tbl, {}),
                            primary_keys=pks_by_table.get(tbl, []),
                            foreign_keys=fks_by_table.get(tbl, {}),
                        )

            return CurrentPostgresSchema(tables=tables)
        except Exception as exc:
            logger.exception("Error al introspeccionar la base de datos de Neon: %s", exc)
            raise NeonMigrationExecutionException(f"No se pudo conectar a Neon para inspeccionar el esquema: {str(exc)}") from exc

    def execute_sql_migration(
        self,
        connection_uri: str,
        statements: list[str],
    ) -> bool:
        if not statements:
            return True

        if not connection_uri:
            raise NeonMigrationExecutionException("No se proporcionó la connection URI de Neon.")

        try:
            with psycopg.connect(connection_uri, autocommit=False, connect_timeout=15) as conn:
                with conn.cursor() as cur:
                    for stmt in statements:
                        clean_stmt = stmt.strip()
                        if clean_stmt:
                            cur.execute(clean_stmt)
                conn.commit()
            return True
        except Exception as exc:
            logger.exception("Error al ejecutar migración SQL en Neon: %s", exc)
            raise NeonMigrationExecutionException(f"Error al ejecutar DDL en Neon: {str(exc)}") from exc
