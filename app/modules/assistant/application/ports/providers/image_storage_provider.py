from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredImage:
    url: str
    public_id: str


class ImageStorageProvider(ABC):
    """Puerto para guardar y compensar una imagen externa."""

    @abstractmethod
    async def upload(self, image_data: bytes, *, public_id: str) -> StoredImage:
        """Sube una imagen bajo un identificador remoto exclusivo del intento."""

    @abstractmethod
    async def delete(self, public_id: str) -> None:
        """Elimina exclusivamente el recurso perteneciente al intento indicado."""
