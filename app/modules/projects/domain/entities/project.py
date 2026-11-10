from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.modules.projects.domain.exceptions import InvalidProjectNameException


class Project:
    """Entidad de dominio que representa un proyecto o lienzo."""

    DEFAULT_NAME = "Nuevo proyecto"
    THUMBNAIL_COOLDOWN_SECONDS = 300  # 5 minutos

    def __init__(
        self,
        id: UUID,
        owner_id: str,
        name: str,
        description: str | None = None,
        thumbnail_url: str | None = None,
        thumbnail_updated_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.owner_id = owner_id
        self.name = self.validate_name(name)
        self.description = description.strip() if description is not None else None
        self.thumbnail_url = thumbnail_url.strip() if thumbnail_url is not None else None
        self.thumbnail_updated_at = thumbnail_updated_at

    @classmethod
    def create(
        cls,
        *,
        owner_id: str,
        name: str = DEFAULT_NAME,
        description: str | None = None,
        thumbnail_url: str | None = None,
        thumbnail_updated_at: datetime | None = None,
    ) -> Project:
        """Constructor con nombre para registrar un nuevo proyecto."""
        return cls(
            id=uuid4(),
            owner_id=owner_id,
            name=name,
            description=description,
            thumbnail_url=thumbnail_url,
            thumbnail_updated_at=thumbnail_updated_at,
        )

    def can_update_thumbnail(self, now: datetime) -> bool:
        """Determina si la miniatura puede actualizarse respetando el cooldown de 5 minutos."""
        if self.thumbnail_updated_at is None:
            return True
        return (now - self.thumbnail_updated_at).total_seconds() >= self.THUMBNAIL_COOLDOWN_SECONDS

    def update_thumbnail(self, thumbnail_url: str, updated_at: datetime) -> None:
        """Actualiza la URL de la miniatura y su timestamp de actualización."""
        self.thumbnail_url = thumbnail_url.strip()
        self.thumbnail_updated_at = updated_at

    def update_info(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        thumbnail_url: str | None = None,
    ) -> None:
        """Actualiza parcialmente los datos del proyecto."""
        if name is not None:
            self.name = self.validate_name(name)
        if description is not None:
            self.description = description.strip()
        if thumbnail_url is not None:
            self.thumbnail_url = thumbnail_url.strip()

    def is_owner(self, user_id: str) -> bool:
        """Verifica si el usuario indicado es el propietario."""
        return self.owner_id == user_id

    @staticmethod
    def validate_name(name: str) -> str:
        """Valida que el nombre sea válido y no esté vacío."""
        if not isinstance(name, str):
            raise InvalidProjectNameException("El nombre del proyecto debe ser texto.")
        normalized = name.strip()
        if not normalized:
            raise InvalidProjectNameException("El nombre del proyecto no puede estar vacío.")
        if len(normalized) > 255:
            raise InvalidProjectNameException("El nombre del proyecto no puede superar los 255 caracteres.")
        return normalized
