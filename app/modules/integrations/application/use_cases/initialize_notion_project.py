from dataclasses import dataclass
from uuid import UUID

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    ModelRole,
)
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionIntegrationProvider,
    NotionProjectWelcomeContent,
)
from app.modules.integrations.application.queries.get_notion_integration_status import (
    NotionIntegrationStatusDTO,
)
from app.modules.integrations.application.services.integration_crypto_service import (
    IntegrationCryptoService,
)
from app.modules.integrations.application.services.notion_project_snapshot_builder import (
    NotionProjectSnapshotBuilder,
)
from app.modules.integrations.domain.enums.integration_provider import (
    IntegrationProvider,
)
from app.modules.integrations.domain.exceptions import (
    NotionIntegrationNotConfiguredException,
    NotionInvalidCredentialsException,
    NotionProjectAlreadyInitializedException,
)
from app.modules.integrations.domain.repositories.project_integration_repository import (
    ProjectIntegrationRepository,
)
from app.shared.application.unit_of_work import UnitOfWorkPort


@dataclass(frozen=True, slots=True)
class InitializeNotionProjectCommand:
    """Comando para inicializar la página raíz y base de datos de tareas en Notion."""

    project_id: UUID
    user_id: str
    description: str


class InitializeNotionProjectUseCase:
    """Inicializa por única vez el espacio de Notion para un proyecto (exclusivo OWNER)."""

    def __init__(
        self,
        access_policy: ProjectAccessPolicy,
        integration_repository: ProjectIntegrationRepository,
        crypto_service: IntegrationCryptoService,
        snapshot_builder: NotionProjectSnapshotBuilder,
        notion_provider: NotionIntegrationProvider,
        ai_provider: AiProvider,
        uow: UnitOfWorkPort,
    ) -> None:
        self.access_policy = access_policy
        self.integration_repository = integration_repository
        self.crypto_service = crypto_service
        self.snapshot_builder = snapshot_builder
        self.notion_provider = notion_provider
        self.ai_provider = ai_provider
        self.uow = uow

    def execute(self, command: InitializeNotionProjectCommand) -> NotionIntegrationStatusDTO:
        # 1. Autorización: Exclusivo OWNER
        self.access_policy.ensure_owner_access(command.project_id, command.user_id)

        # 2. Verificar que exista configuración activa
        integration = self.integration_repository.find_by_project_and_provider(
            command.project_id,
            IntegrationProvider.NOTION,
        )
        if integration is None or not integration.encrypted_api_key:
            raise NotionIntegrationNotConfiguredException()

        # 3. Invariante: Bloqueo de reinicialización (solo permitido una vez)
        integration.ensure_can_initialize()

        # 4. Descifrar API Key y obtener parent_page_id
        api_key = self.crypto_service.decrypt(integration.encrypted_api_key)
        parent_page_id = integration.parent_page_id
        if not parent_page_id:
            # Si no estaba en config, resolver la primera accesible
            _, parent_page_id, _ = self.notion_provider.validate_api_key(api_key)
            if not parent_page_id:
                raise NotionInvalidCredentialsException("No se encontró una página padre accesible en Notion.")

        # 5. Obtener snapshot completo del diagrama y colaboradores en un solo lote
        snapshot = self.snapshot_builder.build_snapshot(command.project_id)

        # 6. Usar la IA para contrastar la descripción breve con las clases reales
        welcome_heading = f"Bienvenido al Espacio de {snapshot.project_name}"
        classes_summary_text = "\n".join(
            f"- {c['name']} con atributos: {', '.join(c['attributes'])}"
            for c in snapshot.classes
        ) or "Sin clases modeladas aún."

        ai_prompt = (
            f"El usuario está inicializando la documentación en Notion para el proyecto '{snapshot.project_name}'.\n"
            f"Descripción proporcionada por el usuario: '{command.description.strip()}'.\n"
            f"Clases actuales en el diagrama UML:\n{classes_summary_text}\n\n"
            f"Genera un resumen ejecutivo breve y profesional (1 o 2 párrafos) que dé la bienvenida al espacio de Notion, "
            f"explique el propósito del sistema integrando la descripción del usuario con las entidades modeladas, "
            f"y oriente a los colaboradores sobre cómo documentar tareas y evolucionar el diseño. Responde solo con el texto plano del resumen."
        )

        try:
            req = AiRequest(
                model_role=ModelRole.MAIN,
                messages=(
                    AiMessage(
                        role="system",
                        content="Eres un arquitecto de software redactando la bienvenida y visión de arquitectura en Notion.",
                    ),
                    AiMessage(role="user", content=ai_prompt),
                ),
                purpose="notion_project_initialization",
                max_output_tokens=600,
                enable_reasoning=False,
            )

            if hasattr(self.ai_provider, "complete"):
                import asyncio
                import inspect
                res = self.ai_provider.complete(req)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            ai_resp = executor.submit(asyncio.run, res).result()
                    else:
                        ai_resp = asyncio.run(res)
                else:
                    ai_resp = res
                executive_desc = getattr(ai_resp, "text", getattr(ai_resp, "content", "")).strip()
            elif hasattr(self.ai_provider, "request"):
                ai_resp = self.ai_provider.request(req)
                executive_desc = getattr(ai_resp, "text", getattr(ai_resp, "content", "")).strip()
            else:
                executive_desc = ""

            if not executive_desc:
                executive_desc = (
                    f"{command.description.strip()}\n\n"
                    f"Este espacio centraliza la documentación y las tareas del modelo de datos de {snapshot.project_name}."
                )
        except Exception:
            executive_desc = (
                f"{command.description.strip()}\n\n"
                f"Este espacio centraliza la documentación y las tareas del modelo de datos de {snapshot.project_name}."
            )

        welcome_content = NotionProjectWelcomeContent(
            welcome_heading=welcome_heading,
            executive_description=executive_desc,
            team_members=snapshot.collaborator_names,
            diagram_classes_summary=snapshot.classes,
        )

        # 7. Crear vía MCP en Notion la página raíz y la base de datos de tareas
        workspace = self.notion_provider.initialize_project_workspace(
            api_key=api_key,
            parent_page_id=parent_page_id,
            project_name=snapshot.project_name,
            welcome_content=welcome_content,
        )

        # 8. Marcar la integración como inicializada y confirmar la transacción
        integration.mark_notion_initialized(
            page_id=workspace.page_id,
            database_id=workspace.database_id,
            page_url=workspace.page_url,
            initial_description=command.description.strip(),
        )
        self.integration_repository.save(integration)
        self.uow.commit()

        return NotionIntegrationStatusDTO(
            project_id=integration.project_id,
            provider=integration.provider.value,
            has_api_key=True,
            is_initialized=True,
            notion_page_id=integration.external_page_id,
            notion_tasks_database_id=integration.external_database_id,
            notion_page_url=integration.notion_page_url,
        )
