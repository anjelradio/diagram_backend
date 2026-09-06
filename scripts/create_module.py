#!/usr/bin/env python3
"""
scripts/create_module.py

Generador CLI de módulos para el scaffold (Arquitectura Hexagonal + DDD en app/modules).

Uso:
    python scripts/create_module.py <nombre_modulo>

Ejemplo:
    python scripts/create_module.py catalog
"""

import sys
from pathlib import Path


def snake_to_pascal(snake_str: str) -> str:
    return "".join(part.capitalize() for part in snake_str.split("_"))


def create_module(module_name: str) -> None:
    # ── 1. Validación de nombre ───────────────────────────────────────────────
    clean_name = module_name.strip().lower().replace("-", "_")
    if not clean_name.isidentifier():
        print(f"❌ Error: '{module_name}' no es un identificador válido de Python (usa snake_case).")
        sys.exit(1)

    root_dir = Path(__file__).resolve().parent.parent
    module_dir = root_dir / "app" / "modules" / clean_name
    pascal_name = snake_to_pascal(clean_name)
    url_slug = clean_name.replace("_", "-")

    if module_dir.exists():
        print(f"⚠️  El módulo '{clean_name}' ya existe en: {module_dir}")
        sys.exit(1)

    print(f"🚀 Creando módulo '{clean_name}' ({pascal_name}) en: {module_dir.relative_to(root_dir)}...\n")

    # ── 2. Creación de directorios ───────────────────────────────────────────
    dirs = [
        # Domain
        module_dir / "domain" / "entities",
        module_dir / "domain" / "value_objects",
        module_dir / "domain" / "repositories",
        # Application
        module_dir / "application" / "use_cases",
        module_dir / "application" / "queries",
        module_dir / "application" / "ports",
        # Infrastructure
        module_dir / "infrastructure" / "persistence" / "models",
        module_dir / "infrastructure" / "persistence" / "mappers",
        module_dir / "infrastructure" / "persistence" / "repositories",
        module_dir / "infrastructure" / "persistence" / "readers",
        module_dir / "infrastructure" / "api" / "schemas",
        module_dir / "infrastructure" / "api" / "routers",
        module_dir / "infrastructure" / "external",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        # Crear __init__.py en cada carpeta de paquete
        init_file = d / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Paquete del módulo."""\n', encoding="utf-8")

    # __init__.py raíz del módulo y capas
    (module_dir / "__init__.py").write_text(f'"""Módulo {clean_name}."""\n', encoding="utf-8")
    (module_dir / "domain" / "__init__.py").write_text('"""Capa de Dominio."""\n', encoding="utf-8")
    (module_dir / "application" / "__init__.py").write_text('"""Capa de Aplicación."""\n', encoding="utf-8")
    (module_dir / "infrastructure" / "__init__.py").write_text('"""Capa de Infraestructura."""\n', encoding="utf-8")
    (module_dir / "infrastructure" / "persistence" / "__init__.py").write_text('"""Persistencia."""\n', encoding="utf-8")
    (module_dir / "infrastructure" / "api" / "__init__.py").write_text('"""Adaptador API."""\n', encoding="utf-8")

    # ── 3. Plantillas de archivos iniciales ───────────────────────────────────

    # A. domain/exceptions.py
    exceptions_content = f'''"""Excepciones de dominio para el módulo {clean_name}."""

from app.shared.domain.exceptions import NotFoundException, ValidationException


class {pascal_name}NotFoundException(NotFoundException):
    code = "{clean_name.upper()}_NOT_FOUND"
    message = "El recurso solicitado de {clean_name} no fue encontrado."


class Invalid{pascal_name}DataException(ValidationException):
    code = "INVALID_{clean_name.upper()}_DATA"
    message = "Los datos proporcionados para {clean_name} no son válidos."
'''
    (module_dir / "domain" / "exceptions.py").write_text(exceptions_content, encoding="utf-8")

    # B. domain/value_objects/sample_code.py
    vo_content = f'''"""Value Objects de {clean_name}."""

from dataclasses import dataclass
from app.shared.domain.value_object import ValueObject
from app.modules.{clean_name}.domain.exceptions import Invalid{pascal_name}DataException


@dataclass(frozen=True, slots=True)
class {pascal_name}Code(ValueObject):
    """Código identificador único del negocio (inmutable)."""
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper() if isinstance(self.value, str) else ""
        self._set_attr("value", normalized)
        self.validate()

    def validate(self) -> None:
        if not self.value or len(self.value) < 3:
            raise Invalid{pascal_name}DataException("El código debe tener al menos 3 caracteres.")
'''
    (module_dir / "domain" / "value_objects" / f"{clean_name}_code.py").write_text(vo_content, encoding="utf-8")

    # C. domain/entities/sample_entity.py
    entity_content = f'''"""Entidad principal de {clean_name}."""

from uuid import UUID, uuid4
from app.modules.{clean_name}.domain.value_objects.{clean_name}_code import {pascal_name}Code


class {pascal_name}:
    """
    Entidad de dominio.
    - __init__: Reconstrucción técnica desde persistencia.
    - @classmethod create: Fábrica con intención de negocio.
    """

    def __init__(
        self,
        id: UUID,
        name: str,
        code: {pascal_name}Code,
        is_active: bool = True,
    ) -> None:
        self.id = id
        self.name = name
        self.code = code
        self.is_active = is_active

    @classmethod
    def create(cls, *, name: str, code: {pascal_name}Code) -> "{pascal_name}":
        """Fábrica de creación de negocio."""
        return cls(
            id=uuid4(),
            name=name.strip(),
            code=code,
            is_active=True,
        )

    def deactivate(self) -> None:
        self.is_active = False

    def activate(self) -> None:
        self.is_active = True
'''
    (module_dir / "domain" / "entities" / f"{clean_name}.py").write_text(entity_content, encoding="utf-8")

    # D. domain/repositories/repository_interface.py
    repo_port_content = f'''"""Contrato de repositorio de dominio (sin prefijo I)."""

from typing import Protocol
from uuid import UUID
from app.modules.{clean_name}.domain.entities.{clean_name} import {pascal_name}


class {pascal_name}Repository(Protocol):
    """Puerto secundario para la persistencia de {pascal_name}."""

    def get_by_id(self, id: UUID) -> {pascal_name} | None:
        """Obtiene la entidad por su UUID."""
        ...

    def save(self, entity: {pascal_name}) -> None:
        """Persiste o actualiza la entidad."""
        ...

    def delete(self, id: UUID) -> None:
        """Elimina la entidad."""
        ...
'''
    (module_dir / "domain" / "repositories" / f"{clean_name}_repository.py").write_text(repo_port_content, encoding="utf-8")

    # E. application/dtos.py
    dtos_content = f'''"""Data Transfer Objects (DTOs) de {clean_name}."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Create{pascal_name}Command:
    name: str
    code: str


@dataclass(frozen=True)
class {pascal_name}DTO:
    id: UUID
    name: str
    code: str
    is_active: bool
'''
    (module_dir / "application" / "dtos.py").write_text(dtos_content, encoding="utf-8")

    # F. infrastructure/persistence/models/model.py
    model_content = f'''"""Modelo de tabla SQLModel para persistencia de {clean_name}."""

from sqlmodel import Field
from app.shared.infrastructure.db.base_model import BaseModel


class {pascal_name}Model(BaseModel, table=True):
    __tablename__ = "{clean_name}s"

    name: str = Field(index=True)
    code: str = Field(unique=True, index=True)
'''
    (module_dir / "infrastructure" / "persistence" / "models" / f"{clean_name}_model.py").write_text(model_content, encoding="utf-8")

    # G. infrastructure/api/schemas/schemas.py
    schemas_content = f'''"""Esquemas Pydantic para la API HTTP de {clean_name}."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class Create{pascal_name}Request(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=3, max_length=50)


class {pascal_name}Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    is_active: bool
'''
    (module_dir / "infrastructure" / "api" / "schemas" / f"{clean_name}_schemas.py").write_text(schemas_content, encoding="utf-8")

    # H. infrastructure/api/routers/router.py
    router_content = f'''"""Endpoints FastAPI para el módulo {clean_name}."""

from fastapi import APIRouter
from app.core.dependencies import CurrentUser, DBSession

router = APIRouter()


@router.get("/", summary="Listar elementos de {clean_name}")
def list_{clean_name}s(db: DBSession, user: CurrentUser):
    """Ruta protegida con CurrentUser (funciona con o sin roles de Better Auth)."""
    return {{"module": "{clean_name}", "user_id": user.user_id, "items": []}}
'''
    (module_dir / "infrastructure" / "api" / "routers" / f"{clean_name}_router.py").write_text(router_content, encoding="utf-8")

    # ── 4. Mensaje de éxito e instrucciones ──────────────────────────────────
    print(f"✅ ¡Módulo '{clean_name}' generado exitosamente!")
    print("\n" + "=" * 70)
    print("📌 PASOS SIGUIENTES PARA REGISTRAR TU MÓDULO:")
    print("=" * 70)
    print(f"\n1. Registra el modelo SQLModel en 'app/shared/infrastructure/db/models.py':")
    print(f"   from app.modules.{clean_name}.infrastructure.persistence.models.{clean_name}_model import {pascal_name}Model")
    print(f"\n2. Registra el router en 'app/main.py':")
    print(f"   from app.modules.{clean_name}.infrastructure.api.routers.{clean_name}_router import router as {clean_name}_router")
    print(f"   app.include_router({clean_name}_router, prefix=\"/api/{url_slug}\", tags=[\"{pascal_name}\"])")
    print("\n3. Si usas migraciones de Alembic:")
    print(f"   alembic revision --autogenerate -m \"add {clean_name}s table\"")
    print("   alembic upgrade head")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/create_module.py <nombre_modulo>")
        sys.exit(1)
    create_module(sys.argv[1])
