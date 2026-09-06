import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BaseModel(SQLModel):
    """
    Modelo base de persistencia para SQLModel.
    Todas las tablas del sistema heredarán de aquí.

    Campos incluidos:
    - id            → UUID v4 generado automáticamente (PK)
    - state         → soft-delete flag (True = activo)
    - created_date  → timestamp de creación (UTC con timezone)
    - modified_date → timestamp de última modificación (actualizado automáticamente en cada UPDATE)
    - deleted_date  → timestamp de eliminación lógica (nullable)
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    state: bool = Field(default=True, index=True)

    created_date: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=utc_now),
    )
    modified_date: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=utc_now,
            onupdate=utc_now,
        ),
    )
    deleted_date: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    def soft_delete(self) -> None:
        """Marca el registro como inactivo y registra la fecha de eliminación."""
        now = utc_now()
        self.state = False
        self.deleted_date = now
        self.modified_date = now

    def restore(self) -> None:
        """Restaura un registro eliminado lógicamente."""
        self.state = True
        self.deleted_date = None
        self.modified_date = utc_now()
