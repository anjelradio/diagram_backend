"""Excepciones de dominio para el módulo de asistente IA."""

from app.shared.domain.exceptions import (
    ConflictException,
    DomainException,
    NotFoundException,
    ValidationException,
)


class AgentActivityNotFoundException(NotFoundException):
    """La actividad del asistente solicitada no existe."""

    code = "AGENT_ACTIVITY_NOT_FOUND"
    message = "La actividad del asistente no fue encontrada o no está disponible."


class InvalidAudioFormatException(ValidationException):
    """El formato del archivo de audio no es compatible con el asistente."""

    code = "INVALID_AUDIO_FORMAT"
    message = "El formato del archivo de audio no es compatible."


class InvalidImageFormatException(ValidationException):
    """El formato o tamaño del archivo de imagen no es compatible con el asistente."""

    code = "INVALID_IMAGE_FORMAT"
    message = "El formato de imagen no es compatible o el archivo excede el tamaño máximo permitido (10 MB)."


class AgentInterpretationFailedException(ValidationException):
    """El modelo de IA no pudo extraer o estructurar acciones comprensibles."""

    code = "AGENT_INTERPRETATION_FAILED"
    message = "El asistente no pudo interpretar la orden solicitada. Intente con una orden más clara."


class AiServiceUnavailableException(DomainException):
    """El proveedor externo de IA no está disponible o agotó sus reintentos."""

    code = "AI_SERVICE_UNAVAILABLE"
    message = "El servicio de IA no está disponible en este momento."


class AgentActionValidationException(ValidationException):
    """Una o más acciones propuestas por el asistente fallaron la validación de dominio."""

    code = "AGENT_ACTION_VALIDATION_ERROR"
    message = "Una o más acciones propuestas por el asistente no son válidas."


class AgentAlreadyActiveException(ConflictException):
    """Ya existe un proceso de asistente en ejecución sobre el mismo proyecto."""

    code = "ACTIVE_ACTIVITY_CONFLICT"
    message = "Ya existe una actividad del asistente en progreso para este proyecto."
