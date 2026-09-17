from datetime import datetime
from uuid import UUID, uuid4

from app.modules.assistant.domain.enums.agent_activity_state import (
    AgentActivityState,
)


class AgentActivity:
    """Entidad de dominio que representa una sesión de trabajo del asistente sobre un proyecto."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        transcription: str | None = None,
        resume: str | None = None,
        image_url: str | None = None,
        state: AgentActivityState = AgentActivityState.IN_PROGRESS,
        created_date: datetime | None = None,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.transcription = transcription
        self.resume = resume
        self.image_url = image_url
        self.state = state
        self.created_date = created_date

    @classmethod
    def create(
        cls,
        project_id: UUID,
        image_url: str | None = None,
    ) -> "AgentActivity":
        """Fábrica de negocio: genera UUID y estado inicial IN_PROGRESS."""
        return cls(
            id=uuid4(),
            project_id=project_id,
            transcription=None,
            resume=None,
            image_url=image_url,
            state=AgentActivityState.IN_PROGRESS,
        )

    def finish(self, transcription: str | None = None, resume: str = "") -> None:
        """Marca la actividad como finalizada exitosamente con su transcripción y resumen."""
        self.transcription = transcription
        self.resume = resume
        self.state = AgentActivityState.FINISHED

    def fail(
        self,
        transcription: str | None = None,
        resume: str | None = None,
    ) -> None:
        """Marca la actividad como fallida."""
        if transcription is not None:
            self.transcription = transcription
        if resume is not None:
            self.resume = resume
        self.state = AgentActivityState.FAILED

    def cancel(self) -> None:
        """Cancela la actividad del asistente."""
        self.state = AgentActivityState.CANCELLED
