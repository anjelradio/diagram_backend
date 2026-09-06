# Guía de Estructura de Módulos (Arquitectura Hexagonal & DDD)

Este scaffold está diseñado para construir sistemas modulares limpios y desacoplados. Cada módulo representa un Bounded Context y organiza su código en las tres capas clásicas: **Domain**, **Application** e **Infrastructure**.

---

## 📁 Estructura Oficial de un Módulo

```text
app/modules/<nombre_modulo>/
├── domain/
│   ├── entities/              # Clases de dominio (clases puras o AggregateRoot)
│   │   ├── student.py         # Constructor técnico + métodos de fábrica @classmethod
│   │   └── course.py
│   ├── value_objects/         # Objetos de valor inmutables (heredan de ValueObject)
│   │   ├── phone_number.py    # Con validate() y normalización si aplica
│   │   └── registration_no.py
│   ├── repositories/          # Interfaces / Contratos de repositorios
│   │   └── student_repository.py  # class StudentRepository(Protocol)
│   └── exceptions.py          # Excepciones de negocio propias del módulo
│
├── application/
│   ├── use_cases/             # Comandos u orquestación que mutan estado
│   │   ├── register_student.py
│   │   └── update_student_phone.py
│   ├── queries/               # Consultas optimizadas de lectura (CQRS)
│   │   ├── get_student_by_id.py
│   │   └── list_active_students.py
│   ├── ports/                 # Puertos secundarios adicionales (ej. Notifier, Storage)
│   └── dtos.py                # Data Transfer Objects (Request / Response internos)
│
└── infrastructure/
    ├── persistence/           # Adaptadores de base de datos
    │   ├── models/            # Tablas SQLModel (heredan de BaseModel)
    │   │   └── student_model.py
    │   ├── mappers/           # Mapeo bidireccional entre Model de BD y Entidad de Dominio
    │   │   └── student_mapper.py
    │   ├── repositories/      # Implementación del puerto de dominio con SQLModel
    │   │   └── sqlmodel_student_repository.py
    │   └── readers/           # (Opcional) Lecturas directas SQL para queries de alto rendimiento
    │       └── student_reader.py
    │
    ├── api/                   # Adaptador primario: HTTP / FastAPI
    │   ├── schemas/           # Esquemas Pydantic v2 para validación del request/response HTTP
    │   │   └── student_schemas.py
    │   └── routers/           # FastAPI APIRouter con endpoints y dependencias
    │       └── student_router.py
    │
    └── external/              # (Opcional) Clientes HTTP externos, pasarelas de pago, SDKs
        └── sms_client.py
```

---

## ⚡ Generación Rápida con CLI
Puedes generar toda esta estructura en 1 segundo usando el generador:
```bash
python scripts/create_module.py <nombre_modulo>
```

---

## 📐 Convenciones y Buenas Prácticas

### 1. Convención de Nombres (Sin prefijo `I`)
- **No usar `I` para interfaces o protocolos.**
- Interfaces en `domain/repositories/`:
  - `StudentRepository` (Protocol) $\rightarrow$ NO `IStudentRepository`.
  - `BookRepository` (Protocol) $\rightarrow$ NO `IBookRepository`.
- Implementaciones en `infrastructure/persistence/repositories/`:
  - `SqlModelStudentRepository` o `PostgresStudentRepository`.
- Puertos compartidos:
  - `UnitOfWork` (Protocol en `app.shared.application.ports`).
  - `EventBus` (Clase base abstracta en `app.shared.domain.event_bus`).
  - `Repository[T, ID]` (Protocol genérico en `app.shared.application.ports`).

---

### 2. Entidades: Constructor vs Métodos de Fábrica (`@classmethod`)
- **`__init__`**: Se reserva para la hidratación/reconstrucción técnica desde la persistencia (cuando el repositorio lee columnas de la base de datos).
- **`@classmethod`** (ej. `register(...)`, `create(...)`): Expresa la **intención de negocio**. Valida reglas iniciales, genera IDs y setea valores por defecto.

```python
# app/modules/student/domain/entities/student.py
from uuid import UUID, uuid4
from app.modules.student.domain.value_objects.phone_number import PhoneNumberBO

class Student:
    def __init__(
        self,
        id: UUID,
        name: str,
        phone: PhoneNumberBO,
        is_active: bool = True,
    ) -> None:
        self.id = id
        self.name = name
        self.phone = phone
        self.is_active = is_active

    @classmethod
    def register(cls, *, name: str, phone: PhoneNumberBO) -> "Student":
        """Fábrica de negocio: genera UUID y estado inicial."""
        return cls(id=uuid4(), name=name.strip(), phone=phone, is_active=True)

    def change_phone(self, new_phone: PhoneNumberBO) -> None:
        self.phone = new_phone

    def deactivate(self) -> None:
        self.is_active = False
```

---

### 3. ¿Cuándo heredar de `AggregateRoot`?
- **Solo cuando la entidad deba emitir Domain Events a otros módulos o al Event Bus.**
- Si el módulo es autosuficiente y ninguna acción requiere notificar a otros módulos, la entidad debe ser una clase normal de Python (no hereda de nada).
- `SqlModelUnitOfWork.track(entity)` es inteligente: si le pasas una entidad normal, la guarda en BD sin intentar despachar eventos; si hereda de `AggregateRoot`, recoge sus eventos y los despacha al confirmar la transacción.

---

### 4. Value Objects (`ValueObject`)
- Heredar siempre de `app.shared.domain.value_object.ValueObject`.
- Usar `@dataclass(frozen=True)` o `@dataclass(frozen=True, slots=True)`.
- Si solo valida invariantes: implementar `validate(self)`.
- Si normaliza strings/valores: usar `self._set_attr("nombre_campo", valor)` en `__post_init__` antes de `self.validate()`.

```python
# app/modules/student/domain/value_objects/phone_number.py
from dataclasses import dataclass
from app.shared.domain.value_object import ValueObject
from app.modules.student.domain.exceptions import InvalidPhoneNumberException

@dataclass(frozen=True, slots=True)
class PhoneNumberBO(ValueObject):
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip() if isinstance(self.value, str) else ""
        self._set_attr("value", normalized)
        self.validate()

    def validate(self) -> None:
        if not self.value.isdigit() or not (7 <= len(self.value) <= 9):
            raise InvalidPhoneNumberException("Teléfono inválido.")
```

---

### 5. Registrar el Módulo en el Sistema
Cuando crees un nuevo módulo, solo debes conectarlo en dos puntos:
1. **Base de Datos (Alembic y SQLModel)**: En [app/shared/infrastructure/db/models.py](file:///home/anjelmuser/in_rainbows/scaffolds/fastapi-scaffoldcito/app/shared/infrastructure/db/models.py):
   ```python
   from app.modules.student.infrastructure.persistence.models.student_model import StudentModel
   ```
2. **Rutas HTTP**: En [app/main.py](file:///home/anjelmuser/in_rainbows/scaffolds/fastapi-scaffoldcito/app/main.py):
   ```python
   from app.modules.student.infrastructure.api.routers.student_router import router as student_router
   app.include_router(student_router, prefix="/api/students", tags=["Students"])
   ```
