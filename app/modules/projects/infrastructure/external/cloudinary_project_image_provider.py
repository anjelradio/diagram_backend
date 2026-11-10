import asyncio
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader

from app.core.config import settings
from app.modules.projects.application.ports.providers.project_image_storage_provider import (
    ProjectImageStorageProvider,
)


class CloudinaryProjectImageProvider(ProjectImageStorageProvider):
    """Adaptador de infraestructura para almacenar miniaturas de proyectos en Cloudinary."""

    FOLDER = "diagrama"

    def __init__(self) -> None:
        self._configured = all(
            (
                settings.CLOUDINARY_CLOUD_NAME.strip(),
                settings.CLOUDINARY_API_KEY.strip(),
                settings.CLOUDINARY_API_SECRET.strip(),
            )
        )
        if self._configured:
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
                secure=True,
            )

    def _get_public_id(self, project_id: str) -> str:
        return f"{self.FOLDER}/project_{project_id}"

    async def upload_thumbnail(self, image_data: bytes, *, project_id: str) -> str:
        """Sube la imagen a la carpeta 'diagrama', reemplazando la miniatura previa."""
        if not self._configured:
            raise RuntimeError("Cloudinary is not configured in environment settings")

        public_id = self._get_public_id(project_id)
        response = await asyncio.to_thread(
            cloudinary.uploader.upload,
            image_data,
            public_id=public_id,
            unique_filename=False,
            overwrite=True,
            resource_type="image",
            timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
        )

        url = str(response.get("secure_url", ""))
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Cloudinary returned an invalid secure image URL")

        return url

    async def delete_thumbnail(self, *, project_id: str) -> None:
        """Elimina la miniatura asociada al proyecto si existe en Cloudinary."""
        if not self._configured:
            return

        public_id = self._get_public_id(project_id)
        try:
            await asyncio.to_thread(
                cloudinary.uploader.destroy,
                public_id,
                resource_type="image",
                invalidate=True,
                timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
            )
        except Exception:
            # Silenciar error en caso de que no existiera el activo
            pass
