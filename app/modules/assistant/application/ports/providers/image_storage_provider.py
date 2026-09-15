from abc import ABC, abstractmethod


class ImageStorageProvider(ABC):
    """Puerto abstracto para el almacenamiento externo de imágenes."""

    @abstractmethod
    async def upload(self, image_data: bytes, filename: str) -> str:
        """Sube una imagen y retorna su URL pública accesible."""
        ...
