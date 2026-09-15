import asyncio
import cloudinary
import cloudinary.uploader

from app.core.config import settings
from app.modules.assistant.application.ports.providers.image_storage_provider import (
    ImageStorageProvider,
)


class CloudinaryImageProvider(ImageStorageProvider):
    """Implementación de ImageStorageProvider utilizando el servicio Cloudinary."""

    def __init__(self) -> None:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

    async def upload(self, image_data: bytes, filename: str) -> str:
        """Sube la imagen en un hilo secundario y devuelve la secure_url."""
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: cloudinary.uploader.upload(
                image_data,
                public_id=filename,
                resource_type="image",
            ),
        )
        return str(response.get("secure_url", ""))
