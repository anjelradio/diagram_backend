from pydantic import BaseModel, Field


class SpringBootGenerationRequest(BaseModel):
    """Petición opcional para personalizar la generación del backend Spring Boot."""

    package_name: str | None = Field(
        default=None,
        description="Nombre del paquete Java raíz (ej. com.empresa.proyecto)",
    )
    artifact_id: str | None = Field(
        default=None,
        description="Identificador del artefacto Maven",
    )
    database_name: str | None = Field(
        default=None,
        description="Nombre de la base de datos PostgreSQL",
    )
