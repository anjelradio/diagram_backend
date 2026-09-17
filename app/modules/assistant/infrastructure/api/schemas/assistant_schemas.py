from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class AgentActivityListItemRead(BaseModel):
    """Resumen de actividad para el historial del asistente."""

    id: UUID = Field(description="Identificador único de la actividad")
    project_id: UUID = Field(description="Identificador del proyecto")
    transcription: str | None = Field(
        default=None, description="Transcripción del audio escuchado por la IA"
    )
    resume: str | None = Field(
        default=None, description="Resumen o explicación redactada por el asistente"
    )
    image_url: str | None = Field(
        default=None, description="URL de la imagen asociada, si aplica"
    )
    state: str = Field(
        description="Estado de la actividad (IN_PROGRESS, FINISHED, FAILED, CANCELLED)"
    )
    created_date: datetime = Field(
        description="Fecha y hora UTC de creación de la actividad"
    )


class ActionResultRead(BaseModel):
    """Representación del resultado individual de una acción ejecutada por el asistente."""

    type: str = Field(description="Tipo de acción ejecutada")
    status: str = Field(description="Estado de la ejecución (executed, skipped, failed)")
    summary: str = Field(description="Resumen explicativo de la acción realizada")


class VoiceCommandResultRead(BaseModel):
    """Respuesta pública con el resultado completo de la orden de voz procesada."""

    activity_id: UUID = Field(description="Identificador único de la actividad del asistente")
    state: str = Field(description="Estado final de la actividad (FINISHED, FAILED, etc.)")
    transcription: str | None = Field(default=None, description="Transcripción del audio escuchado por la IA")
    resume: str | None = Field(default=None, description="Resumen o explicación redactada por el asistente")
    actions_count: int = Field(description="Cantidad de acciones ejecutadas sobre el diagrama")
    actions: list[ActionResultRead] = Field(
        default_factory=list,
        description="Listado secuencial de acciones ejecutadas",
    )


class ImageCommandResultRead(BaseModel):
    """Respuesta pública con el resultado del análisis y recreación de diagrama por imagen."""

    activity_id: UUID = Field(description="Identificador único de la actividad del asistente")
    state: str = Field(description="Estado final de la actividad (FINISHED, FAILED, etc.)")
    transcription: str | None = Field(default=None, description="Transcripción asociada, si aplica")
    resume: str | None = Field(default=None, description="Resumen o explicación redactada por el asistente")
    image_url: str | None = Field(default=None, description="URL pública de la imagen procesada")
    actions_count: int = Field(description="Cantidad de acciones ejecutadas sobre el diagrama")
    actions: list[ActionResultRead] = Field(
        default_factory=list,
        description="Listado secuencial de acciones ejecutadas",
    )
