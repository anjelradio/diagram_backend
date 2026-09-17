from app.shared.domain.exceptions import ValidationException


class EmptyDiagramException(ValidationException):
    """El diagrama no contiene ninguna clase para generar el backend."""

    code = "EMPTY_DIAGRAM"
    message = "El diagrama debe contener al menos una clase para poder generar el backend."


class CodeGenerationException(ValidationException):
    """Falla general durante el proceso de generación de código."""

    code = "CODE_GENERATION_FAILED"
    message = "No fue posible generar el código del proyecto debido a inconsistencias en el diagrama."
