from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class InvitationResponse(BaseModel):
    """Respuesta que contiene el código de invitación y su fecha de expiración."""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(description="Código alfanumérico de 10 caracteres para unirse al proyecto")
    expires_at: datetime = Field(description="Fecha y hora UTC de vencimiento de la invitación")


class JoinProjectRequest(BaseModel):
    """Petición para unirse a un proyecto mediante código de invitación."""

    code: str = Field(
        min_length=10,
        max_length=10,
        description="Código de invitación de 10 caracteres",
    )


class JoinProjectResponse(BaseModel):
    """Respuesta con el identificador del proyecto al unirse mediante código."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID = Field(
        description="Identificador único del proyecto al que se unió"
    )
