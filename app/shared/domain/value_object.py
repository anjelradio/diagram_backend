from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValueObject:
    """
    Clase base inmutable para todos los Value Objects del dominio.
    La igualdad se basa en sus atributos estructurales, no en identidad.

    Reglas de uso:
    --------------
    1. Si el Value Object solo valida invariantes (sin alterar el valor):
       Basta con definir `validate(self)` en la subclase; `__post_init__` la llamará
       automáticamente.

       Ejemplo (Solo validación):
       ::
           @dataclass(frozen=True)
           class DiscountPercentage(ValueObject):
               value: int

               def validate(self) -> None:
                   if not (0 <= self.value <= 100):
                       raise InvalidDiscountException("El porcentaje debe estar entre 0 y 100.")

    2. Si el Value Object normaliza datos (ej. .strip(), .upper()):
       Al ser una clase con `frozen=True`, Python no permite reasignar atributos directamente.
       Usa `self._set_attr("value", normalized)` dentro de `__post_init__` antes de llamar a `self.validate()`.

       Ejemplo (Normalización + Validación):
       ::
           @dataclass(frozen=True, slots=True)
           class PhoneNumberBO(ValueObject):
               value: str

               def __post_init__(self) -> None:
                   normalized = self.value.strip() if isinstance(self.value, str) else ""
                   self._set_attr("value", normalized)
                   self.validate()

               def validate(self) -> None:
                   if not self.value.isdigit() or not (7 <= len(self.value) <= 9):
                       raise InvalidPhoneNumberException()
    """

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Sobrescribir en subclases para validar invariantes del negocio."""
        pass

    def _set_attr(self, name: str, value: Any) -> None:
        """
        Asigna un atributo en una instancia inmutable (frozen=True).
        Útil exclusivamente dentro de `__post_init__` para almacenar valores normalizados.
        """
        object.__setattr__(self, name, value)

    def __str__(self) -> str:
        """Retorna la representación en string del valor si existe, o del objeto."""
        if hasattr(self, "value"):
            return str(self.value)
        return super().__str__()
