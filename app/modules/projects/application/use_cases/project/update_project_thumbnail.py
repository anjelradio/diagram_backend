import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.projects.application.ports.providers.project_image_storage_provider import (
    ProjectImageStorageProvider,
)
from app.modules.projects.domain.entities.project import Project
from app.modules.projects.domain.exceptions import ProjectNotFoundException
from app.shared.infrastructure.db.base_model import utc_now


class UpdateProjectThumbnailUseCase:
    """Caso de uso para actualizar la miniatura del proyecto respetando el cooldown de 5 minutos y existencia de clases."""

    def __init__(
        self,
        project_repository: Any,
        image_storage_provider: ProjectImageStorageProvider,
        access_checker: Any | None = None,
        diagram_class_repository: Any | None = None,
        uow: Any | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.image_storage_provider = image_storage_provider
        self.access_checker = access_checker
        self.diagram_class_repository = diagram_class_repository
        self.uow = uow

    async def execute(
        self,
        *,
        project_id: UUID,
        user_id: str,
        image_data: bytes,
    ) -> dict[str, Any]:
        # 1. Obtener proyecto
        project = None
        if hasattr(self.project_repository, "find_by_id"):
            project = self.project_repository.find_by_id(project_id)
        elif hasattr(self.project_repository, "get_by_id"):
            project = await self.project_repository.get_by_id(project_id)

        if project is None:
            raise ProjectNotFoundException()

        # 2. Verificar permisos de acceso (OWNER o EDITOR)
        if self.access_checker is not None:
            if hasattr(self.access_checker, "resolve_access"):
                access = self.access_checker.resolve_access(project_id, user_id)
                role = access.access_role.value if hasattr(access.access_role, "value") else str(access.access_role)
                if role not in ("OWNER", "EDITOR"):
                    raise ProjectNotFoundException()
            elif hasattr(self.access_checker, "can_edit_project"):
                can_edit = await self.access_checker.can_edit_project(project_id, user_id)
                if not can_edit:
                    raise ProjectNotFoundException()

        now = utc_now()

        # 3. Comprobar existencia de al menos una clase en el proyecto
        if self.diagram_class_repository is not None:
            has_classes = True
            if hasattr(self.diagram_class_repository, "list_by_project_id"):
                classes = self.diagram_class_repository.list_by_project_id(project_id)
                has_classes = len(classes) > 0
            elif hasattr(self.diagram_class_repository, "has_classes"):
                has_classes = self.diagram_class_repository.has_classes(project_id)

            if not has_classes:
                return {
                    "project_id": project.id,
                    "thumbnail_url": project.thumbnail_url,
                    "thumbnail_updated_at": project.thumbnail_updated_at,
                    "updated": False,
                }

        # 4. Comprobar regla de 5 minutos (cooldown)
        if not project.can_update_thumbnail(now):
            return {
                "project_id": project.id,
                "thumbnail_url": project.thumbnail_url,
                "thumbnail_updated_at": project.thumbnail_updated_at,
                "updated": False,
            }

        # 5. Subir a Cloudinary
        secure_url = await self.image_storage_provider.upload_thumbnail(
            image_data,
            project_id=str(project.id),
        )

        # 5. Actualizar en dominio y guardar en base de datos
        project.update_thumbnail(secure_url, now)
        save_res = self.project_repository.save(project)
        if asyncio.iscoroutine(save_res):
            await save_res

        if self.uow is not None and hasattr(self.uow, "commit"):
            self.uow.commit()

        return {
            "project_id": project.id,
            "thumbnail_url": project.thumbnail_url,
            "thumbnail_updated_at": project.thumbnail_updated_at,
            "updated": True,
        }
