from __future__ import annotations

from uuid import UUID, uuid4

from app.modules.projects.domain.exceptions import InvalidProjectNameException


class Project:
    """Entidad de dominio que representa un proyecto o lienzo."""

    DEFAULT_NAME = "Nuevo proyecto"

    def __init__(
        self,
        id: UUID,
        owner_id: str,
        name: str,
        description: str | None = None,
        thumbnail_url: str | None = None,
    ) -> None:
        self.id = id
        self.owner_id = owner_id
        self.name = self.validate_name(name)
        self.description = description.strip() if description is not None else None
        self.thumbnail_url = thumbnail_url.strip() if thumbnail_url is not None else None

    @classmethod
    def create(
        cls,
        *,
        owner_id: str,
        name: str = DEFAULT_NAME,
        description: str | None = None,
        thumbnail_url: str | None = None,
    ) -> Project:
        """Constructor con nombre para registrar un nuevo proyecto."""
        return cls(
            id=uuid4(),
            owner_id=owner_id,
            name=name,
            description=description,
            thumbnail_url=thumbnail_url,
        )

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
