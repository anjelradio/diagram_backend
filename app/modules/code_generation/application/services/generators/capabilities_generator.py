import json
from uuid import UUID

from app.modules.code_generation.application.services.generators.java_identifier_sanitizer import (
    map_standard_type,
    sanitize_class_attributes,
    to_kebab_case,
    to_pascal_case,
    to_snake_case,
)
from app.modules.code_generation.application.services.generators.relation_resolver import (
    resolve_entity_dependencies,
)
from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)
from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


def _get_dummy_value(java_type: str, field_name: str):
    field_lower = field_name.lower()
    if java_type == "UUID":
        return "c56a4180-65aa-42ec-a945-5fd21dec0538"
    if java_type in ("Integer", "Long", "Short"):
        if "edad" in field_lower:
            return 25
        if "stock" in field_lower or "cantidad" in field_lower:
            return 10
        return 1
    if java_type in ("Double", "Float", "BigDecimal"):
        if "precio" in field_lower or "costo" in field_lower or "monto" in field_lower:
            return 49.99
        return 10.5
    if java_type == "Boolean":
        return True
    if java_type in ("LocalDate", "LocalDateTime", "Date"):
        return "2026-01-01"
    # String
    if "email" in field_lower or "correo" in field_lower:
        return "usuario@ejemplo.com"
    if "nombre" in field_lower:
        return f"Ejemplo {field_name.capitalize()}"
    if "telefono" in field_lower:
        return "+123456789"
    return f"Valor de {field_name}"


class CapabilitiesGenerator:
    """Generador del archivo capabilities.json v2 compacto para asistentes de IA locales y clientes móviles."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(
        self,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto],
    ) -> GeneratedFile:
        all_classes_map: dict[UUID, DiagramClassSnapshotDto] = {
            c.id: c for c in classes
        }

        entities_list = []

        for c in classes:
            class_name = to_pascal_case(c.name)
            table_name = to_snake_case(c.name)
            endpoint = f"/{to_kebab_case(c.name)}"

            sanitized_attrs = sanitize_class_attributes(c.attributes)
            attr_by_orig_name = {a.name: a for a in c.attributes}

            fields_list = []
            seen_field_names = set()

            for sa in sanitized_attrs:
                orig_attr = attr_by_orig_name.get(sa.original_name)
                data_type_raw = orig_attr.data_type if orig_attr else sa.java_type
                std_type = map_standard_type(data_type_raw)

                field_def: dict[str, object] = {
                    "name": sa.field_name,
                    "type": std_type,
                }
                if sa.is_primary_key:
                    field_def["primary_key"] = True
                    field_def["required"] = True
                else:
                    field_def["required"] = not sa.is_nullable
                    # Inferencia de valor default si no es requerido
                    name_lower = sa.field_name.lower()
                    if sa.is_nullable:
                        if std_type == "INTEGER" and ("stock" in name_lower or "cantidad" in name_lower):
                            field_def["default"] = 0
                        elif std_type == "DATETIME" and "fecha" in name_lower:
                            field_def["default"] = "CURRENT_TIMESTAMP"

                fields_list.append(field_def)
                seen_field_names.add(sa.field_name)

            # Dependencias ManyToOne legítimas
            deps = resolve_entity_dependencies(c, all_classes_map, relations)
            relationships_list = []

            for dep in deps:
                # Agregar campo de clave foránea a la lista de fields si no está presente
                if dep.fk_field_name not in seen_field_names:
                    fields_list.append({
                        "name": dep.fk_field_name,
                        "type": "UUID",
                        "required": not dep.is_nullable,
                    })
                    seen_field_names.add(dep.fk_field_name)

                relationships_list.append({
                    "field_name": dep.fk_field_name,
                    "target_entity": dep.referenced_class_name,
                    "target_table": to_snake_case(dep.referenced_class_name),
                    "type": "ManyToOne",
                    "required": not dep.is_nullable,
                })

            entities_list.append({
                "name": class_name,
                "table_name": table_name,
                "endpoint": endpoint,
                "fields": fields_list,
                "relationships": relationships_list,
            })

        doc = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "project_name": self.config.project_name,
            "version": "2.0.0",
            "base_url": f"http://localhost:{self.config.server_port}",
            "api_prefix": "/api",
            "standard_crud": {
                "enabled": True,
                "operations": ["CREATE", "READ_ALL", "READ_BY_ID", "UPDATE", "DELETE"],
                "response_envelope": "message",
            },
            "entities": entities_list,
        }

        return GeneratedFile(
            relative_path="capabilities.json",
            content=json.dumps(doc, indent=2, ensure_ascii=False),
        )
