from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from app.modules.assistant.application.ports.providers.ai_provider import AiToolDefinition
from app.modules.assistant.application.services.execution.tool_registry import (
    ProgressReporter,
    RegisteredTool,
    ToolRegistry,
)
from app.modules.integrations.application.use_cases.sync_neon_database import (
    SyncNeonDatabaseCommand,
    SyncNeonDatabaseUseCase,
)
from app.shared.domain.exceptions import DomainException

logger = logging.getLogger(__name__)


class NeonAgentTools:
    """Herramientas del asistente para sincronizar la base de datos en Neon."""

    def __init__(
        self,
        *,
        project_id: UUID,
        user_id: str,
        sync_neon_use_case: SyncNeonDatabaseUseCase,
    ) -> None:
        self.project_id = project_id
        self.user_id = user_id
        self.sync_neon_use_case = sync_neon_use_case

    def register(self, registry: ToolRegistry) -> None:
        """Registra la herramienta sync_neon_database en el ToolRegistry."""
        registry.register(
            RegisteredTool(
                definition=AiToolDefinition(
                    name="sync_neon_database",
                    description=(
                        "Sincroniza la base de datos PostgreSQL en Neon como un espejo exacto del diagrama UML actual (Versus completo). "
                        "Calcula deterministamente las diferencias estructurales y aplica las migraciones transaccionales en Neon. "
                        "Solo ejecutable por el propietario (OWNER) del proyecto."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                handler=self._sync_database,
                mutating=True,
            )
        )

    async def _sync_database(
        self,
        args: dict[str, Any],
        report: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        op_id = f"op-neon-sync-{uuid4().hex[:8]}"
        if report:
            await report(
                {
                    "operation_id": op_id,
                    "action_kind": "SYNC_NEON_DATABASE",
                    "status": "validated",
                    "target_name": "Base de datos Neon",
                }
            )

        try:
            summary = self.sync_neon_use_case.execute(
                SyncNeonDatabaseCommand(
                    project_id=self.project_id,
                    user_id=self.user_id,
                )
            )

            res = {
                "operation_id": op_id,
                "status": "applied",
                "has_changes": summary.has_changes,
                "created_tables": summary.created_tables,
                "dropped_tables": summary.dropped_tables,
                "added_columns": summary.added_columns,
                "dropped_columns": summary.dropped_columns,
                "altered_columns": summary.altered_columns,
                "added_foreign_keys": summary.added_foreign_keys,
                "dropped_foreign_keys": summary.dropped_foreign_keys,
                "message": (
                    "La base de datos en Neon fue sincronizada con éxito reflejando el diagrama UML actual."
                    if summary.has_changes
                    else "La base de datos en Neon ya se encuentra idéntica y al día con el diagrama actual (sin cambios pendientes)."
                ),
            }

            if report:
                await report(
                    {
                        "operation_id": op_id,
                        "action_kind": "SYNC_NEON_DATABASE",
                        "status": "applied",
                        "target_name": "Base de datos Neon",
                        "entity_refs": [{"type": "neon_database", "id": str(self.project_id)}],
                        "summary": summary.to_dict(),
                    }
                )

            return res

        except DomainException as exc:
            logger.warning("Error de dominio al sincronizar Neon: %s", exc)
            res = {
                "operation_id": op_id,
                "status": "rejected",
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
            if report:
                await report(
                    {
                        "operation_id": op_id,
                        "action_kind": "SYNC_NEON_DATABASE",
                        "status": "rejected",
                        "target_name": "Base de datos Neon",
                        "error": str(exc),
                    }
                )
            return res
        except Exception as exc:
            logger.exception("Error inesperado al sincronizar base de datos en Neon: %s", exc)
            res = {
                "operation_id": op_id,
                "status": "rejected",
                "error_code": "NeonSyncExecutionException",
                "error": f"Error al sincronizar con Neon: {str(exc)}",
            }
            if report:
                await report(
                    {
                        "operation_id": op_id,
                        "action_kind": "SYNC_NEON_DATABASE",
                        "status": "rejected",
                        "target_name": "Base de datos Neon",
                        "error": str(exc),
                    }
                )
            return res
