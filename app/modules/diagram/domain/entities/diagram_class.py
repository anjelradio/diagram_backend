import math
from uuid import UUID

from app.modules.diagram.domain.exceptions import (
    InvalidDiagramClassNameException,
    InvalidDiagramCoordinatesException,
)


class DiagramClass:
    """Entidad de dominio que representa una clase en el lienzo del diagrama."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        name: str,
        position_x: float,
        position_y: float,
    ) -> None:
        self.id = id
        self.project_id = project_id
        self._name = self._validate_name(name)
        self._position_x, self._position_y = self._validate_coordinates(
            position_x, position_y
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def position_x(self) -> float:
        return self._position_x

    @property
    def position_y(self) -> float:
        return self._position_y

    @classmethod
    def _validate_name(cls, name: str) -> str:
        if not isinstance(name, str):
            raise InvalidDiagramClassNameException()
        cleaned = name.strip()
        if not cleaned or len(cleaned) > 255:
            raise InvalidDiagramClassNameException()
        return cleaned

    @classmethod
    def _validate_coordinates(cls, x: float, y: float) -> tuple[float, float]:
        try:
            x_float = float(x)
            y_float = float(y)
        except (ValueError, TypeError):
            raise InvalidDiagramCoordinatesException()

        if not math.isfinite(x_float) or not math.isfinite(y_float):
            raise InvalidDiagramCoordinatesException()

        return x_float, y_float

    @classmethod
    def create(
        cls,
        id: UUID,
        project_id: UUID,
        name: str,
        position_x: float,
        position_y: float,
    ) -> "DiagramClass":
        """Fábrica nombrada para crear una nueva clase con UUIDv4 originado en el cliente."""
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            position_x=position_x,
            position_y=position_y,
        )

    def rename(self, new_name: str) -> None:
        """Actualiza el nombre de la clase validando que no esté vacío."""
        self._name = self._validate_name(new_name)

    def move(self, new_x: float, new_y: float) -> None:
        """Actualiza la posición absoluta de la clase en el lienzo."""
        self._position_x, self._position_y = self._validate_coordinates(new_x, new_y)
