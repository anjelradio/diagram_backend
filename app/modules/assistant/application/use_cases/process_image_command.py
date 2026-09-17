import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.exc import IntegrityError

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
)
from app.modules.assistant.application.ports.providers.image_storage_provider import (
    ImageStorageProvider,
)
from app.modules.assistant.application.services.action_executor import (
    ActionExecutor,
    AtomicBatchUnitOfWork,
)
from app.modules.assistant.application.services.action_planner import (
    ActionPlanner,
)
from app.modules.assistant.domain.entities.agent_activity import AgentActivity
from app.modules.assistant.domain.enums.agent_activity_state import AgentActivityState
from app.modules.assistant.domain.exceptions import (
    AgentActionValidationException,
    AgentAlreadyActiveException,
    AgentInterpretationFailedException,
    InvalidImageFormatException,
)
from app.modules.assistant.domain.repositories.agent_activity_repository import (
    AgentActivityRepository,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramSnapshotDto,
    DiagramSnapshotReader,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.diagram.infrastructure.realtime.connection_manager import (
    ConnectionManager,
)
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


@dataclass(frozen=True, slots=True)
class ProcessImageCommand:
    project_id: UUID
    user_id: str
    image_data: bytes
    image_mime_type: str
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessImageCommandResultDto:
    activity_id: UUID
    state: str
    transcription: str | None
    resume: str | None
    actions_count: int
    actions: list[dict[str, str]]
    image_url: str | None = None


class ProcessImageCommandUseCase:
    """Orquesta la interpretación de diagramas por imagen, validación de acciones, ejecución atómica y notificación."""

    def __init__(
        self,
        access_policy: DiagramAccessPolicy,
        ai_provider: AiProvider,
        agent_activity_repository: AgentActivityRepository,
        diagram_snapshot_reader: DiagramSnapshotReader,
        action_planner: ActionPlanner,
        action_executor: ActionExecutor,
        batch_uow: AtomicBatchUnitOfWork,
        real_uow: SqlModelUnitOfWork,
        connection_manager: ConnectionManager,
        image_storage_provider: ImageStorageProvider | None = None,
    ) -> None:
        self.access_policy = access_policy
        self.ai_provider = ai_provider
        self.agent_activity_repository = agent_activity_repository
        self.diagram_snapshot_reader = diagram_snapshot_reader
        self.action_planner = action_planner
        self.action_executor = action_executor
        self.batch_uow = batch_uow
        self.real_uow = real_uow
        self.connection_manager = connection_manager
        self.image_storage_provider = image_storage_provider

    async def execute(
        self, command: ProcessImageCommand
    ) -> ProcessImageCommandResultDto:
        # 1. Validar formato y tamaño de imagen
        normalized_mime = command.image_mime_type.split(";")[0].strip().lower()
        if (
            normalized_mime not in SUPPORTED_IMAGE_MIME_TYPES
            and not normalized_mime.startswith("image/")
        ):
            raise InvalidImageFormatException()

        if len(command.image_data) == 0 or len(command.image_data) > MAX_IMAGE_SIZE_BYTES:
            raise InvalidImageFormatException()

        # 2. Validar permiso de edición en el proyecto (lanza DiagramWriteForbiddenException si no tiene)
        self.access_policy.ensure_write_access(
            command.project_id, command.user_id, ignore_agent_lock=True
        )

        # 3. Reservar la única actividad activa del proyecto.
        if self.agent_activity_repository.find_active_by_project_id(command.project_id):
            raise AgentAlreadyActiveException()

        # Opcional: Subir imagen al storage externo
        image_url: str | None = None
        if self.image_storage_provider:
            try:
                ext = "png" if "png" in normalized_mime else "webp" if "webp" in normalized_mime else "jpg"
                filename = f"diagram_{command.project_id}_{ext}"
                image_url = await self.image_storage_provider.upload(
                    image_data=command.image_data,
                    filename=filename,
                )
            except Exception as exc:
                logger.warning("No se pudo almacenar la imagen en storage externo: %s", exc)

        activity = AgentActivity.create(
            project_id=command.project_id,
            image_url=image_url,
        )
        self.agent_activity_repository.save(activity)
        try:
            # La restricción parcial de la BD cubre la carrera entre dos solicitudes.
            self.real_uow.session.commit()
        except IntegrityError as exc:
            self.real_uow.session.rollback()
            raise AgentAlreadyActiveException() from exc

        terminal_sent = False

        async def publish_terminal(state: str) -> None:
            """Publica un único cierre correlacionado para esta actividad."""
            nonlocal terminal_sent
            if terminal_sent:
                return
            await self.connection_manager.broadcast_agent_finished(
                command.project_id, command.user_id, activity.id, state
            )
            terminal_sent = True

        # 4. Notificar bloqueo a colaboradores por WebSocket
        try:
            await self.connection_manager.broadcast_agent_lock(
                command.project_id, command.user_id, activity.id
            )
        except Exception as exc:
            activity.fail(resume=str(exc))
            self.agent_activity_repository.save(activity)
            self.real_uow.session.commit()
            raise

        try:
            # 5. Obtener snapshot completo del diagrama
            classes = (
                self.diagram_snapshot_reader.get_classes_with_attributes_by_project_id(
                    command.project_id
                )
            )
            relations = (
                self.diagram_snapshot_reader.get_relations_by_project_id(
                    command.project_id
                )
            )
            snapshot = DiagramSnapshotDto(classes=classes, relations=relations)

            max_snapshot_classes = 120
            snapshot_classes = classes[:max_snapshot_classes]
            snapshot_dict = {
                "classes": [
                    {
                        "id": str(c.id),
                        "name": c.name.strip(),
                        "position_x": c.position_x,
                        "position_y": c.position_y,
                        "attributes": [
                            {
                                "id": str(a.id),
                                "name": a.name.strip()[:64],
                                "data_type": a.data_type,
                                "position": a.position,
                                "is_primary_key": a.is_primary_key,
                                "is_nullable": a.is_nullable,
                                "is_foreign_key": a.is_foreign_key,
                            }
                            for a in c.attributes
                        ],
                    }
                    for c in snapshot_classes
                ],
                "relations": [
                    {
                        "id": str(r.id),
                        "name": r.name,
                        "relation_type": r.relation_type,
                        "source": {
                            "class_id": str(r.source.class_id),
                            "handle": r.source.handle,
                        },
                        "target": {
                            "class_id": str(r.target.class_id),
                            "handle": r.target.handle,
                        },
                        "source_cardinality": r.source_cardinality,
                        "target_cardinality": r.target_cardinality,
                    }
                    for r in relations
                ],
            }

            # 6. Consultar IA con fallback
            available_data_types = [dt.value for dt in DiagramAttributeDataType]
            available_relation_types = [rt.value for rt in DiagramRelationType]
            available_cardinalities = [cd.value for cd in DiagramCardinality]

            ai_result = await self.ai_provider.interpret_image_command(
                image_data=command.image_data,
                image_mime_type=normalized_mime,
                diagram_snapshot=snapshot_dict,
                available_data_types=available_data_types,
                available_relation_types=available_relation_types,
                available_cardinalities=available_cardinalities,
                prompt=command.prompt,
            )

            # 7. Si no hay acciones generadas por la IA
            if not ai_result.actions:
                activity.finish(
                    transcription=ai_result.transcription,
                    resume=ai_result.resume,
                )
                self.agent_activity_repository.save(activity)
                self.real_uow.session.commit()

                await publish_terminal("FINISHED")

                return ProcessImageCommandResultDto(
                    activity_id=activity.id,
                    state="FINISHED",
                    transcription=ai_result.transcription,
                    resume=ai_result.resume,
                    actions_count=0,
                    actions=[],
                    image_url=image_url,
                )

            # 8. Planificar y validar acciones deterministamente
            validated_actions = self.action_planner.plan_actions(
                project_id=command.project_id,
                user_id=command.user_id,
                ai_actions=ai_result.actions,
                snapshot=snapshot,
            )

            # Re-verificar acceso
            self.access_policy.ensure_write_access(
                command.project_id,
                command.user_id,
                ignore_agent_lock=True,
            )

            # 9. Ejecutar acciones en el lote atómico
            executed_actions: list[dict[str, str]] = []
            for va in validated_actions:
                self.action_executor.execute_action(va)
                executed_actions.append(
                    {
                        "type": va.action_type.value,
                        "status": "executed",
                        "summary": va.summary,
                    }
                )

            # 10. Actualizar actividad del asistente y confirmar transacción
            activity.finish(
                transcription=ai_result.transcription,
                resume=ai_result.resume,
            )
            self.agent_activity_repository.save(activity)
            self.real_uow.session.commit()

            # 11. Emitir mutaciones una por una por WebSocket
            for event in self.batch_uow.collected_events:
                payload = {
                    "type": "diagram_mutation",
                    "operation_type": event.operation_type,
                    "data": event.data,
                    "sender_id": "assistant",
                }
                await self.connection_manager.broadcast(
                    command.project_id,
                    payload,
                )
                await asyncio.sleep(0.04)

            # 12. Notificar fin de actividad con éxito
            await publish_terminal("FINISHED")

            return ProcessImageCommandResultDto(
                activity_id=activity.id,
                state="FINISHED",
                transcription=ai_result.transcription,
                resume=ai_result.resume,
                actions_count=len(executed_actions),
                actions=executed_actions,
                image_url=image_url,
            )

        except Exception as exc:
            if isinstance(
                exc,
                (
                    AgentActionValidationException,
                    AgentInterpretationFailedException,
                    AgentAlreadyActiveException,
                ),
            ):
                logger.warning("Comando de imagen rechazado (dominio): %s", exc)
            else:
                logger.error("Error durante el procesamiento del comando de imagen: %s", exc)
            self.batch_uow.rollback()

            transcription = (
                ai_result.transcription if "ai_result" in locals() else None
            )
            if activity.state != AgentActivityState.FINISHED:
                activity.fail(
                    transcription=transcription,
                    resume=str(exc),
                )
                self.agent_activity_repository.save(activity)
                try:
                    self.real_uow.session.commit()
                except Exception:
                    self.real_uow.session.rollback()
                await publish_terminal("FAILED")
            else:
                await publish_terminal("FINISHED")
            raise exc
