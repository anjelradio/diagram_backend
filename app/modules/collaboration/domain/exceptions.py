"""Excepciones de dominio para el módulo de colaboración (miembros e invitaciones)."""

from app.shared.domain.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)


class InvitationNotFoundException(NotFoundException):
    """La invitación solicitada no existe, no pertenece al proyecto o está vencida."""

    code = "INVITATION_NOT_FOUND"
    message = "La invitación no fue encontrada o no está disponible."


class ProjectMemberNotFoundException(NotFoundException):
    """El colaborador no fue encontrado en el proyecto."""

    code = "PROJECT_MEMBER_NOT_FOUND"
    message = "El participante no fue encontrado en este proyecto."


class UserAlreadyMemberException(ConflictException):
    """El usuario ya participa activamente en el proyecto."""

    code = "USER_ALREADY_MEMBER"
    message = "Ya eres un participante activo en este proyecto."


class UserBannedException(ForbiddenException):
    """El usuario ha sido bloqueado en el proyecto y no puede unirse."""

    code = "USER_BANNED"
    message = "Has sido bloqueado en este proyecto y no puedes ingresar."


class CannotJoinOwnProjectException(ConflictException):
    """El propietario del proyecto no puede unirse como colaborador a su propio proyecto."""

    code = "CANNOT_JOIN_OWN_PROJECT"
    message = "El propietario no puede unirse como colaborador a su propio proyecto."


class InvalidInvitationCodeException(ValidationException):
    """El código de invitación debe ser alfanumérico de 10 caracteres."""

    code = "INVALID_INVITATION_CODE"
    message = "El código de invitación debe ser alfanumérico de 10 caracteres."


class InvalidMemberTransitionException(ConflictException):
    """La transición de rol o estado del participante no es válida."""

    code = "INVALID_MEMBER_TRANSITION"
