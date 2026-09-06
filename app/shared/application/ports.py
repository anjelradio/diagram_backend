from typing import Protocol, TypeVar
from uuid import UUID

T = TypeVar("T")
ID = TypeVar("ID", bound=UUID | str)


class UnitOfWork(Protocol):
    """Contrato base que todo Unit of Work debe cumplir (sin prefijo I)."""

    def commit(self) -> None:
        """Persiste los cambios y despacha eventos post-commit."""
        ...

    def rollback(self) -> None:
        """Revierte los cambios pendientes."""
        ...

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        ...


class Repository(Protocol[T, ID]):
    """
    Contrato base genérico para repositorios de dominio (sin prefijo I).
    Cada módulo define sus repositorios específicos en su carpeta domain/repositories/.
    """

    def get_by_id(self, id: ID) -> T | None:
        """Obtiene una entidad por su identificador único."""
        ...

    def save(self, entity: T) -> None:
        """Persiste o actualiza la entidad en el almacenamiento."""
        ...

    def delete(self, id: ID) -> None:
        """Elimina la entidad por su identificador."""
        ...


# Alias de compatibilidad
IUnitOfWork = UnitOfWork
IRepository = Repository
