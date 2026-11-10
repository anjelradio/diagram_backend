from abc import ABC, abstractmethod


class ProjectImageStorageProvider(ABC):
    """Puerto para el almacenamiento y gestión externa de imágenes de proyectos (Cloudinary)."""

    @abstractmethod
    async def upload_thumbnail(self, image_data: bytes, *, project_id: str) -> str:
        """Sube la miniatura del proyecto reemplazando cualquier versión previa y retorna la URL segura."""
        raise NotImplementedError

    @abstractmethod
    async def delete_thumbnail(self, *, project_id: str) -> None:
        """Elimina la miniatura asociada al proyecto si existe."""
        raise NotImplementedError
