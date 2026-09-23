"""Excepciones de dominio para el módulo de proyectos."""

from app.shared.domain.exceptions import (
    DomainException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)


class ProjectNotFoundException(NotFoundException):
    """El proyecto solicitado no existe o fue eliminado."""

    code = "PROJECT_NOT_FOUND"
    message = "El proyecto no fue encontrado o no está disponible."


class ProjectNotOwnedException(ForbiddenException):
    """El usuario no es propietario del proyecto y no tiene permisos para esta acción."""

    code = "PROJECT_NOT_OWNED"
    message = "No tienes permisos de propietario sobre este proyecto."


class InvalidProjectNameException(ValidationException):
    """El nombre del proyecto no cumple con los requisitos de longitud o contenido."""

    code = "INVALID_PROJECT_NAME"


class InvalidProjectFileException(ValidationException):
    """El archivo no contiene un diagrama de clases UML válido compatible con Enterprise Architect."""

    code = "INVALID_PROJECT_FILE"
    message = "El archivo no contiene un diagrama de clases UML válido compatible con Enterprise Architect."


class ProjectExportFailedException(DomainException):
    """Ocurrió un error al generar la exportación XMI del proyecto."""

    code = "PROJECT_EXPORT_FAILED"
    message = "No se pudo generar la exportación XMI del proyecto."

