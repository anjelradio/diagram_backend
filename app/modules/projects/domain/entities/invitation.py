from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.modules.projects.domain.exceptions import InvalidInvitationCodeException


class Invitation:
    """Entidad de dominio que representa un código de invitación temporal para un proyecto."""

    CODE_LENGTH = 10

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        code: str,
        expires_at: datetime,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.code = self.validate_code(code)
        self.expires_at = expires_at

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        code: str,
        expires_at: datetime,
    ) -> Invitation:
        """Constructor con nombre para emitir una nueva invitación."""
        return cls(
            id=uuid4(),
            project_id=project_id,
            code=code,
            expires_at=expires_at,
        )

    def renew(self, *, code: str, expires_at: datetime) -> None:
        """Reemplaza el código y la fecha de expiración de la invitación."""
        self.code = self.validate_code(code)
        self.expires_at = expires_at

    def is_expired(self, now: datetime | None = None) -> bool:
        """Determina si la invitación ya venció respecto a la fecha/hora UTC dada."""
        current_time = now or datetime.now(timezone.utc)
        # Asegurar comparación timezone-aware
        if self.expires_at.tzinfo is None:
            expires_at_aware = self.expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at_aware = self.expires_at
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        return current_time >= expires_at_aware

    def is_valid(self, now: datetime | None = None) -> bool:
        """Determina si la invitación está vigente."""
        return not self.is_expired(now)

    @staticmethod
    def validate_code(code: str) -> str:
        """Valida que el código sea alfanumérico y de exactamente 10 caracteres."""
        if not isinstance(code, str):
            raise InvalidInvitationCodeException("El código de invitación debe ser texto.")
        normalized = code.strip()
        if len(normalized) != Invitation.CODE_LENGTH or not normalized.isalnum():
            raise InvalidInvitationCodeException(
                f"El código de invitación debe ser alfanumérico de {Invitation.CODE_LENGTH} caracteres."
            )
        return normalized
