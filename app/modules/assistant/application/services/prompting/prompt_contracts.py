"""Contratos inmutables y resolución de dependencias para el sistema modular de prompts."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from math import ceil
from typing import Any


class PromptContractError(Exception):
    """Error base de contratos de prompting."""


class CircularPolicyDependencyError(PromptContractError):
    """Indica un ciclo en las dependencias de políticas."""


class MissingPolicyDependencyError(PromptContractError):
    """Indica que una política depende de un identificador no registrado."""


@dataclass(frozen=True, slots=True)
class PromptPolicy:
    """Política o regla modular inmutable de instrucciones."""

    id: str
    version: str
    text: str
    phases: frozenset[str]
    capabilities: frozenset[str]
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("El id de la política no puede estar vacío.")
        if not self.version or not self.version.strip():
            raise ValueError("La versión de la política no puede estar vacía.")
        if not self.text or not self.text.strip():
            raise ValueError("El texto de la política no puede estar vacío.")


@dataclass(frozen=True, slots=True)
class PromptCompositionContext:
    """Contexto inmutable para la selección y composición de instrucciones.
    
    No confiere permisos adicionales; sirve exclusivamente como descriptor del
    estado y capacidades requeridas en la fase actual de inferencia.
    """

    phase: str
    authorized_actions: frozenset[str] = field(default_factory=frozenset)
    derived_capabilities: frozenset[str] = field(default_factory=frozenset)
    has_image_evidence: bool = False
    has_continuation: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.phase or not self.phase.strip():
            raise ValueError("La fase del contexto no puede estar vacía.")


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """Paquete de instrucciones compuesto e inmutable listo para inferencia."""

    version: str
    policy_ids: tuple[str, ...]
    system_text: str
    estimated_tokens: int

    @classmethod
    def create(
        cls,
        *,
        version: str,
        policy_ids: tuple[str, ...],
        system_text: str,
        estimated_tokens: int | None = None,
    ) -> "PromptBundle":
        if estimated_tokens is None:
            # Estimación conservadora en español (~4 caracteres por token)
            estimated_tokens = max(1, ceil(len(system_text) / 4))
        return cls(
            version=version,
            policy_ids=policy_ids,
            system_text=system_text,
            estimated_tokens=estimated_tokens,
        )


def resolve_policy_dependencies(
    catalog: Mapping[str, PromptPolicy],
    selected_ids: Iterable[str],
) -> tuple[PromptPolicy, ...]:
    """Ordena topológicamente las políticas seleccionadas incluyendo dependencias transitivas.

    Garantiza que toda dependencia aparezca antes de la política que la requiere,
    sin duplicados y detectando ciclos o dependencias ausentes.
    """
    resolved: list[PromptPolicy] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def _dfs(policy_id: str) -> None:
        if policy_id in visiting:
            raise CircularPolicyDependencyError(
                f"Ciclo detectado en las dependencias de políticas de prompting: '{policy_id}'."
            )
        if policy_id in visited:
            return

        visiting.add(policy_id)
        if policy_id not in catalog:
            raise MissingPolicyDependencyError(
                f"La política '{policy_id}' no existe en el catálogo de prompting."
            )

        policy = catalog[policy_id]
        for dep_id in policy.dependencies:
            _dfs(dep_id)

        visiting.remove(policy_id)
        visited.add(policy_id)
        resolved.append(policy)

    for pid in selected_ids:
        _dfs(pid)

    return tuple(resolved)
