"""Excepciones de dominio del módulo de asistente."""

from enum import Enum

from app.shared.domain.exceptions import ConflictException, DomainException, ValidationException


class AgentMessageAlreadyExistsException(ConflictException):
    """El UUID enviado ya identifica otro mensaje."""

    code = "MESSAGE_ID_CONFLICT"
    message = "Ya existe un mensaje con ese identificador."


class AgentAlreadyActiveException(ConflictException):
    """El usuario ya tiene una ejecución en este proyecto."""

    code = "ACTIVE_MESSAGE_EXISTS"
    message = "Ya tienes una solicitud en ejecución en este proyecto."


class InvalidAgentMessageException(ValidationException):
    """El texto o la imagen no cumple el contrato de creación del mensaje."""

    code = "INVALID_AGENT_MESSAGE"


class ImageStorageUnavailableException(DomainException):
    """Cloudinary no está disponible o no pudo guardar la imagen."""

    code = "IMAGE_STORAGE_UNAVAILABLE"
    message = "El almacenamiento de imágenes no está disponible."


class AgentMessagePersistenceException(DomainException):
    """No se pudo confirmar el mensaje en la base de datos."""

    code = "AGENT_MESSAGE_PERSISTENCE_FAILED"
    message = "No se pudo guardar el mensaje. Inténtalo de nuevo."


class AiProviderErrorReason(str, Enum):
    """Causas seguras de una respuesta inválida del proveedor."""

    UNSPECIFIED = "unspecified"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    INVALID_IMAGE_URL = "invalid_image_url"
    INVALID_JSON = "invalid_json"
    RESPONSE_NOT_OBJECT = "response_not_object"
    MISSING_CHOICES = "missing_choices"
    INVALID_CHOICE = "invalid_choice"
    OUTPUT_TRUNCATED = "output_truncated"
    MISSING_MESSAGE = "missing_message"
    INVALID_CONTENT = "invalid_content"
    INVALID_TOOL_CALLS = "invalid_tool_calls"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    EMPTY_RESPONSE = "empty_response"


class AiProviderUnavailableReason(str, Enum):
    """Causas seguras de indisponibilidad del proveedor."""

    UNSPECIFIED = "unspecified"
    MISSING_API_KEY = "missing_api_key"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"


class AiProviderError(DomainException):
    """El proveedor no devolvió una respuesta utilizable."""

    code = "AI_PROVIDER_INVALID_RESPONSE"
    message = "El asistente recibió una respuesta no válida. Inténtalo de nuevo."

    def __init__(
        self, *, reason: AiProviderErrorReason = AiProviderErrorReason.UNSPECIFIED
    ):
        self.reason = (
            reason
            if isinstance(reason, AiProviderErrorReason)
            else AiProviderErrorReason.UNSPECIFIED
        )
        super().__init__()


class AiProviderUnavailableException(DomainException):
    """No fue posible completar la solicitud al proveedor de IA."""

    code = "AI_PROVIDER_UNAVAILABLE"
    message = "El asistente no está disponible temporalmente. Inténtalo de nuevo."

    def __init__(
        self,
        *,
        reason: AiProviderUnavailableReason = AiProviderUnavailableReason.UNSPECIFIED,
        status_code: int | None = None,
    ):
        self.reason = (
            reason
            if isinstance(reason, AiProviderUnavailableReason)
            else AiProviderUnavailableReason.UNSPECIFIED
        )
        self.status_code = status_code
        super().__init__()


class AgentContextException(DomainException):
    """El contexto del usuario no pudo prepararse de forma segura."""

    code = "AGENT_CONTEXT_UNAVAILABLE"
    message = "No se pudo preparar el contexto del asistente. Inténtalo de nuevo."


class AgentProcessingException(DomainException):
    """El procesamiento del mensaje no pudo confirmarse."""

    code = "AGENT_PROCESSING_FAILED"
    message = "No se pudo completar el mensaje. Inténtalo de nuevo."


class ExecutionPlanErrorReason(str, Enum):
    """Motivos seguros para diagnosticar un plan sin registrar su contenido."""

    UNSPECIFIED = "unspecified"
    PLANNER_INVALID_JSON = "planner.invalid_json"
    PLANNER_NOT_OBJECT = "planner.not_object"
    PLANNER_INVALID_GOAL = "planner.invalid_goal"
    PLANNER_INVALID_TASKS = "planner.invalid_tasks"
    PLANNER_TASK_LIMIT = "planner.task_limit_exceeded"
    PLANNER_INVALID_TASK = "planner.invalid_task"
    PLANNER_INVALID_VISUAL_FLAG = "planner.invalid_visual_flag"
    PLANNER_INVALID_TASK_FIELDS = "planner.invalid_task_fields"
    PLANNER_MULTIPLE_ANSWERS = "planner.multiple_answer_tasks"
    PLANNER_MUTATION_DEPENDS_ON_ANSWER = "planner.mutation_depends_on_answer"
    PLAN_INVALID_SERIALIZED = "plan.invalid_serialized"
    PLAN_INVALID_VERSION_OR_STATUS = "plan.invalid_version_or_status"
    PLAN_INVALID_GOAL = "plan.invalid_goal"
    PLAN_LIMIT_EXCEEDED = "plan.task_or_operation_limit"
    PLAN_INVALID_TASK_ID = "plan.invalid_task_id"
    PLAN_DUPLICATE_TASK_ID = "plan.duplicate_task_id"
    PLAN_INVALID_TASK = "plan.invalid_task"
    PLAN_INVALID_DEPENDENCY = "plan.invalid_dependency"
    PLAN_CYCLIC_DEPENDENCY = "plan.cyclic_dependency"
    PLAN_INVALID_OPERATION = "plan.invalid_operation"
    EXECUTOR_MUTATION_DEPENDS_ON_ANSWER = "executor.mutation_depends_on_answer"
    EXECUTOR_UNRESOLVABLE_DEPENDENCIES = "executor.unresolvable_dependencies"


class InvalidExecutionPlanException(ValidationException):
    """El plan tiene una versión, dependencia o estado no permitido."""

    code = "INVALID_EXECUTION_PLAN"
    message = "El plan de ejecución no es válido."

    def __init__(
        self, *, reason: ExecutionPlanErrorReason = ExecutionPlanErrorReason.UNSPECIFIED
    ):
        self.reason = (
            reason if isinstance(reason, ExecutionPlanErrorReason)
            else ExecutionPlanErrorReason.UNSPECIFIED
        )
        super().__init__()


class AgentToolArgumentsException(ValidationException):
    """Los argumentos de una herramienta no cumplen el contrato."""

    code = "INVALID_AGENT_TOOL_ARGUMENTS"
    message = "Los argumentos de la operación no son válidos."


class AgentAmbiguousClassException(ConflictException):
    """La selección visual coincide con varias clases del proyecto."""

    code = "AGENT_AMBIGUOUS_CLASS"

    def __init__(self, name: str, candidate_ids: list[str]):
        self.class_name = name
        self.candidate_ids = candidate_ids[:20]
        super().__init__(f"Hay varias clases llamadas {name}; indica cuál quieres usar.")


class UnknownAgentToolException(ValidationException):
    """Se solicitó una herramienta que no está habilitada."""

    code = "UNKNOWN_AGENT_TOOL"
    message = "La operación solicitada no está disponible."


class UnsupportedAgentToolActionException(ValidationException):
    """La acción solicitada no pertenece al catálogo autorizado del agente."""

    code = "UNSUPPORTED_AGENT_TOOL_ACTION"
    message = "La acción solicitada no está disponible."


class AgentToolLimitException(ValidationException):
    """La herramienta superó el presupuesto permitido."""

    code = "AGENT_TOOL_LIMIT_EXCEEDED"
    message = "La operación excede el límite permitido."


class AgentMemoryCompactionException(DomainException):
    """La memoria no pudo compactarse dentro del presupuesto permitido."""

    code = "AGENT_MEMORY_COMPACTION_FAILED"
    message = "No se pudo preparar la memoria del asistente. Inténtalo de nuevo."


class InvalidAgentUserMemoryException(ValidationException):
    """El resumen de memoria está vacío o supera el límite de almacenamiento."""

    code = "INVALID_AGENT_USER_MEMORY"


class AgentMemoryUpdateException(DomainException):
    """La actualización de memoria falló o no produjo un resultado válido."""

    code = "AGENT_MEMORY_UPDATE_FAILED"
    message = "No se pudo actualizar la memoria del asistente."
