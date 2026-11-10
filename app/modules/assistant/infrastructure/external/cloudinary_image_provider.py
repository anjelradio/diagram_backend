import asyncio
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader

from app.core.config import settings
from app.modules.assistant.application.ports.providers.image_storage_provider import (
    ImageStorageProvider,
    StoredImage,
)
from app.modules.assistant.domain.exceptions import ImageStorageUnavailableException


class CloudinaryImageProvider(ImageStorageProvider):
    """Implementación del almacenamiento externo mediante Cloudinary."""

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

    async def upload(self, image_data: bytes, *, public_id: str) -> StoredImage:
        """Sube la imagen fuera del hilo de la API y devuelve su URL segura."""
        if not self._configured:
            raise ImageStorageUnavailableException()
        try:
            response = await asyncio.to_thread(
                cloudinary.uploader.upload,
                image_data,
                public_id=public_id,
                unique_filename=False,
                overwrite=False,
                resource_type="image",
                timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
            )
            url = str(response.get("secure_url", ""))
            remote_id = str(response.get("public_id", public_id))
            parsed_url = urlparse(url)
            if parsed_url.scheme != "https" or not parsed_url.netloc or not remote_id:
                if remote_id:
                    await asyncio.to_thread(
                        cloudinary.uploader.destroy,
                        remote_id,
                        resource_type="image",
                        invalidate=True,
                    )
                raise ValueError("Cloudinary returned an invalid image URL")
            return StoredImage(url=url, public_id=remote_id)
        except Exception as exc:
            raise ImageStorageUnavailableException() from exc

    async def delete(self, public_id: str) -> None:
        """Elimina exclusivamente el public ID generado por este intento."""
        if not self._configured:
            raise ImageStorageUnavailableException()
        try:
            await asyncio.to_thread(
                cloudinary.uploader.destroy,
                public_id,
                resource_type="image",
                invalidate=True,
                timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise ImageStorageUnavailableException() from exc
