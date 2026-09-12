from __future__ import annotations

from uuid import UUID, uuid4

from app.modules.projects.domain.enums.project_member_role import ProjectMemberRole
from app.modules.projects.domain.enums.project_member_status import ProjectMemberStatus
from app.modules.projects.domain.exceptions import (
    InvalidMemberTransitionException,
    UserAlreadyMemberException,
    UserBannedException,
)


class ProjectMember:
    """Entidad de dominio que representa la participación de un colaborador en un proyecto."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        user_id: str,
        role: ProjectMemberRole,
        status: ProjectMemberStatus,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.user_id = user_id
        self.role = role
        self.status = status

    @classmethod
    def create_reader(
        cls,
        *,
        project_id: UUID,
        user_id: str,
    ) -> ProjectMember:
        """Fábrica de negocio: genera participación inicial como lector activo."""
        return cls(
            id=uuid4(),
            project_id=project_id,
            user_id=user_id,
            role=ProjectMemberRole.READER,
            status=ProjectMemberStatus.ACTIVE,
        )

    def promote_to_editor(self) -> None:
        """Promueve al colaborador a rol EDITOR."""
        if self.status == ProjectMemberStatus.BANNED:
            raise InvalidMemberTransitionException(
                "No se puede cambiar el rol de un participante bloqueado."
            )
        self.role = ProjectMemberRole.EDITOR

    def demote_to_reader(self) -> None:
        """Degrada al colaborador a rol READER."""
        if self.status == ProjectMemberStatus.BANNED:
            raise InvalidMemberTransitionException(
                "No se puede cambiar el rol de un participante bloqueado."
            )
        self.role = ProjectMemberRole.READER

    def change_role(self, new_role: ProjectMemberRole) -> None:
        """Actualiza el rol del colaborador (READER o EDITOR)."""
        if self.status == ProjectMemberStatus.BANNED:
            raise InvalidMemberTransitionException(
                "No se puede cambiar el rol de un participante bloqueado."
            )
        self.role = new_role

    def change_status(self, new_status: ProjectMemberStatus) -> None:
        """Actualiza el estado de participación (REMOVED o BANNED)."""
        if new_status == ProjectMemberStatus.REMOVED:
            self.remove()
        elif new_status == ProjectMemberStatus.BANNED:
            self.ban()
        elif new_status == ProjectMemberStatus.ACTIVE:
            self.reactivate()
        else:
            raise InvalidMemberTransitionException(f"Estado no soportado: {new_status}")

    def remove(self) -> None:
        """Remueve al colaborador del proyecto conservando su historial."""
        self.status = ProjectMemberStatus.REMOVED

    def ban(self) -> None:
        """Bloquea al colaborador para impedir su reingreso."""
        self.status = ProjectMemberStatus.BANNED

    def unban(self) -> None:
        """Desbloquea a un participante previamente bloqueado, reactivando su acceso."""
        if self.status != ProjectMemberStatus.BANNED:
            raise InvalidMemberTransitionException(
                "El participante no se encuentra bloqueado."
            )
        self.status = ProjectMemberStatus.ACTIVE

    def reactivate(self) -> None:
        """Reactiva la membresía de un colaborador previamente removido."""
        if self.status == ProjectMemberStatus.BANNED:
            raise UserBannedException("El usuario está bloqueado y no puede ser reactivado.")
        if self.status == ProjectMemberStatus.ACTIVE:
            raise UserAlreadyMemberException("El usuario ya es un participante activo.")
        self.status = ProjectMemberStatus.ACTIVE

    def is_active(self) -> bool:
        return self.status == ProjectMemberStatus.ACTIVE

    def is_banned(self) -> bool:
        return self.status == ProjectMemberStatus.BANNED

    def is_removed(self) -> bool:
        return self.status == ProjectMemberStatus.REMOVED
