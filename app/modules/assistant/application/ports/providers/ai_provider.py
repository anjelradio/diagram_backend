from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.modules.assistant.domain.enums.agent_action_type import AgentActionType


@dataclass(frozen=True, slots=True)
class AiAction:
    """Acción atómica propuesta por el modelo de IA."""

    type: AgentActionType
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AiInterpretationResult:
    """Resultado estructurado de la interpretación de una orden de IA (voz o imagen)."""

    transcription: str | None
    resume: str
    actions: list[AiAction]


class AiProvider(ABC):
    """Puerto para el proveedor de Inteligencia Artificial."""

    @abstractmethod
    async def interpret_voice_command(
        self,
        audio_data: bytes,
        audio_mime_type: str,
        diagram_snapshot: dict[str, Any],
        available_data_types: list[str],
        available_relation_types: list[str],
        available_cardinalities: list[str],
    ) -> AiInterpretationResult:
        """Interpreta un comando de voz en el contexto del diagrama actual."""
        ...

    @abstractmethod
    async def interpret_image_command(
        self,
        image_data: bytes,
        image_mime_type: str,
        diagram_snapshot: dict[str, Any],
        available_data_types: list[str],
        available_relation_types: list[str],
        available_cardinalities: list[str],
        prompt: str | None = None,
    ) -> AiInterpretationResult:
        """Interpreta un diagrama a partir de una imagen y genera el plan de acciones."""
        ...
