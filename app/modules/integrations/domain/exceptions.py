from app.shared.domain.exceptions import (
    ConflictException,
    DomainException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)


class NotionIntegrationNotConfiguredException(ValidationException):
    """Se lanza cuando el proyecto aún no tiene configurada la integración de Notion."""

    code = "NOTION_INTEGRATION_NOT_CONFIGURED"
    message = "El proyecto aún no tiene una API Key de Notion configurada."


class NotionProjectNotInitializedException(ValidationException):
    """Se lanza cuando se intenta operar tareas en Notion sin haber inicializado la página del proyecto."""

    code = "NOTION_PROJECT_NOT_INITIALIZED"
    message = "El proyecto aún no ha sido inicializado en Notion. El propietario debe inicializarlo primero."


class NotionProjectAlreadyInitializedException(ConflictException):
    """Se lanza cuando se intenta inicializar en Notion un proyecto que ya fue inicializado."""

    code = "NOTION_PROJECT_ALREADY_INITIALIZED"
    message = "El proyecto ya fue inicializado en Notion. Solo se permite inicializar una vez por proyecto."


class NotionInvalidCredentialsException(ValidationException):
    """Se lanza cuando la API Key de Notion es inválida o no tiene acceso a ninguna página."""

    code = "NOTION_INVALID_CREDENTIALS"
    message = "La API Key de Notion es inválida o no tiene páginas autorizadas en el espacio de trabajo."


class NotionTaskOwnershipException(ForbiddenException):
    """Se lanza cuando un usuario intenta modificar o eliminar una tarea de Notion que pertenece a otro colaborador."""

    code = "NOTION_TASK_OWNERSHIP_DENIED"
    message = "No puedes modificar ni eliminar esta tarea de Notion porque pertenece a otro colaborador."


class NotionTaskNotFoundException(NotFoundException):
    """Se lanza cuando la tarea solicitada no existe en la base de datos de Notion del proyecto."""

    code = "NOTION_TASK_NOT_FOUND"
    message = "No se encontró la tarea solicitada en Notion."


class NeonInvalidCredentialsException(ValidationException):
    """Se lanza cuando la API Key de Neon es inválida o no tiene permisos."""

    code = "NEON_INVALID_CREDENTIALS"
    message = "La API Key de Neon es inválida o no tiene acceso a la organización."


class NeonIntegrationNotConfiguredException(ValidationException):
    """Se lanza cuando el proyecto aún no tiene configurada la API Key de Neon."""

    code = "NEON_INTEGRATION_NOT_CONFIGURED"
    message = "El proyecto aún no tiene una API Key de Neon configurada."


class NeonProjectNotInitializedException(ValidationException):
    """Se lanza cuando se intenta sincronizar o consultar la BD en Neon sin haber inicializado el proyecto."""

    code = "NEON_PROJECT_NOT_INITIALIZED"
    message = "El proyecto aún no ha sido inicializado en Neon. El propietario debe inicializarlo primero."


class NeonProjectAlreadyInitializedException(ConflictException):
    """Se lanza cuando se intenta inicializar en Neon un proyecto que ya fue inicializado."""

    code = "NEON_PROJECT_ALREADY_INITIALIZED"
    message = "El proyecto ya fue inicializado en Neon. Para actualizarlo solicita una sincronización."


class NeonDiagramValidationException(ValidationException):
    """Se lanza cuando el diagrama UML no es válido para desplegar en PostgreSQL (vacío, clases/atributos duplicados)."""

    code = "NEON_DIAGRAM_VALIDATION_ERROR"
    message = "El diagrama actual contiene inconsistencias que impiden su despliegue en Neon."


class NeonMigrationExecutionException(DomainException):
    """Se lanza cuando ocurre un error de ejecución DDL en Neon."""

    code = "NEON_MIGRATION_EXECUTION_ERROR"
    message = "Ocurrió un error al ejecutar la migración en Neon."


class NeonOperationForbiddenException(ForbiddenException):
    """Se lanza cuando un usuario no propietario intenta inicializar o sincronizar Neon."""

    code = "NEON_OPERATION_FORBIDDEN"
    message = "Solo el propietario del proyecto puede inicializar o sincronizar la base de datos en Neon."



class NotionExternalServiceException(DomainException):
    """Se lanza ante un fallo de comunicación con el servicio MCP/API de Notion."""

    code = "NOTION_EXTERNAL_SERVICE_ERROR"
    message = "Ocurrió un error al comunicarse con el servicio de Notion."
