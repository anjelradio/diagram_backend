"""Excepciones de dominio para el módulo de diagramas."""

from app.shared.domain.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)


class DiagramWriteForbiddenException(ForbiddenException):
    """El usuario tiene acceso de lectura pero no de escritura al lienzo."""

    code = "WRITE_FORBIDDEN"
    message = "No tienes permisos de edición en este lienzo."


class DiagramAgentLockedException(ConflictException):
    """El lienzo está reservado por una actividad activa del asistente."""

    code = "DIAGRAM_AGENT_LOCKED"
    message = "El lienzo está siendo actualizado por el asistente. Inténtalo de nuevo cuando termine."


class DiagramClassNotFoundException(NotFoundException):
    """La clase de diagrama solicitada no existe."""

    code = "DIAGRAM_CLASS_NOT_FOUND"
    message = "La clase de diagrama no fue encontrada o no está disponible."


class DiagramClassNameAlreadyExistsException(ConflictException):
    """Ya existe una clase con ese nombre en el proyecto."""

    code = "DIAGRAM_CLASS_NAME_CONFLICT"
    message = "Ya existe una clase con ese nombre en este proyecto."


class DiagramClassIdConflictException(ConflictException):
    """El identificador de la clase ya existe pero con datos distintos."""

    code = "DIAGRAM_CLASS_ID_CONFLICT"
    message = "El identificador de la clase ya existe con datos diferentes."


class InvalidDiagramClassNameException(ValidationException):
    """El nombre de la clase de diagrama es inválido."""

    code = "INVALID_DIAGRAM_CLASS_NAME"
    message = "El nombre de la clase no puede estar vacío ni superar los 255 caracteres."


class InvalidDiagramCoordinatesException(ValidationException):
    """Las coordenadas de posición son inválidas."""

    code = "INVALID_DIAGRAM_COORDINATES"
    message = "Las coordenadas de la clase deben ser números finitos."


class DiagramAttributeNotFoundException(NotFoundException):
    """El atributo de diagrama solicitado no existe."""

    code = "DIAGRAM_ATTRIBUTE_NOT_FOUND"
    message = "El atributo de diagrama no fue encontrado o no está disponible."


class DiagramAttributeIdConflictException(ConflictException):
    """El identificador del atributo ya existe pero con datos distintos."""

    code = "DIAGRAM_ATTRIBUTE_ID_CONFLICT"
    message = "El identificador del atributo ya existe con datos diferentes."


class InvalidDiagramAttributeNameException(ValidationException):
    """El nombre del atributo de diagrama es inválido."""

    code = "INVALID_DIAGRAM_ATTRIBUTE_NAME"
    message = "El nombre del atributo no puede estar vacío ni superar los 255 caracteres."


class PrimaryKeyCannotBeDeletedException(ConflictException):
    """La llave primaria de una clase no puede eliminarse."""

    code = "PRIMARY_KEY_CANNOT_BE_DELETED"
    message = "No se puede eliminar la llave primaria de una clase de diagrama."


class PrimaryKeyCannotBeModifiedException(ConflictException):
    """El tipo o la nullabilidad de la llave primaria no pueden modificarse."""

    code = "PRIMARY_KEY_CANNOT_BE_MODIFIED"
    message = "El tipo de dato y la nullabilidad de la llave primaria no pueden modificarse."


class PrimaryKeyCannotBeRepositionedException(ConflictException):
    """La llave primaria no puede reposicionarse fuera de la posición 0."""

    code = "PRIMARY_KEY_CANNOT_BE_REPOSITIONED"
    message = "La llave primaria debe permanecer fija en la posición 0."


class InvalidAttributePositionException(ValidationException):
    """La posición del atributo es inválida."""

    code = "INVALID_ATTRIBUTE_POSITION"
    message = "La posición de un atributo secundario debe ser un entero mayor o igual a 1."


class DiagramRelationNotFoundException(NotFoundException):
    """La relación de diagrama solicitada no existe."""

    code = "DIAGRAM_RELATION_NOT_FOUND"
    message = "La relación de diagrama no fue encontrada o no está disponible."


class DiagramRelationIdConflictException(ConflictException):
    """El identificador de la relación ya existe pero con datos distintos."""

    code = "DIAGRAM_RELATION_ID_CONFLICT"
    message = "El identificador de la relación ya existe con datos diferentes."


class DiagramRelationSelfReferenceException(ValidationException):
    """Una relación no puede conectar una clase consigo misma."""

    code = "DIAGRAM_RELATION_SELF_REFERENCE"
    message = "Una relación no puede tener la misma clase como origen y destino."


class InvalidDiagramRelationNameException(ValidationException):
    """El nombre de la relación es inválido."""

    code = "INVALID_DIAGRAM_RELATION_NAME"
    message = "El nombre de la relación no puede superar los 255 caracteres."


class InvalidDiagramRelationCardinalityException(ValidationException):
    """Las cardinalidades son incompatibles con el tipo de relación."""

    code = "INVALID_DIAGRAM_RELATION_CARDINALITY"
    message = "Las cardinalidades son obligatorias para asociaciones y deben ser nulas para otros tipos."


class InvalidDiagramRelationHandleException(ValidationException):
    """El punto de conexión es inválido."""

    code = "INVALID_DIAGRAM_RELATION_HANDLE"
    message = "El punto de conexión de la relación debe ser uno de los doce handles válidos."


class InvalidDiagramRelationMaterializationException(ValidationException):
    """La materialización del agregado relacional es incoherente."""

    code = "INVALID_DIAGRAM_RELATION_MATERIALIZATION"
    message = "La estructura de materialización no coincide con el tipo o cardinalidad de la relación."


class DuplicateGeneralizationException(ConflictException):
    """Una subclase solo puede participar como origen de una generalización activa."""

    code = "DUPLICATE_GENERALIZATION"
    message = "La subclase ya tiene una relación de generalización activa."


class NonAssociativeRelationNameCannotBeModifiedException(ConflictException):
    """Las relaciones no asociativas deben conservar un nombre vacío y no admiten renombrado."""

    code = "RELATION_NAME_NOT_SUPPORTED"
    message = "Las relaciones no asociativas no admiten nombre."


ManyToManyRelationNameCannotBeModifiedException = NonAssociativeRelationNameCannotBeModifiedException


class ForeignKeyCannotBeDeletedException(ConflictException):
    """Un atributo que actúa como clave foránea no puede eliminarse directamente."""

    code = "FOREIGN_KEY_CANNOT_BE_DELETED"
    message = "No se puede eliminar directamente un atributo derivado de una relación."


class ForeignKeyCannotBeModifiedException(ConflictException):
    """El tipo de dato y nullabilidad de una clave foránea no pueden modificarse."""

    code = "FOREIGN_KEY_CANNOT_BE_MODIFIED"
    message = "El tipo de dato y la nullabilidad de una clave foránea no pueden modificarse."


class ForeignKeyCannotBeRepositionedException(ConflictException):
    """Un atributo de clave foránea no puede reposicionarse manualmente."""

    code = "FOREIGN_KEY_CANNOT_BE_REPOSITIONED"
    message = "Los atributos de clave foránea no pueden reposicionarse manualmente."


class BridgeClassCannotBeDeletedDirectlyException(ConflictException):
    """Una clase puente no puede eliminarse como clase independiente."""

    code = "BRIDGE_CLASS_CANNOT_BE_DELETED_DIRECTLY"
    message = "Una clase puente solo puede eliminarse a través de su relación propietaria."
