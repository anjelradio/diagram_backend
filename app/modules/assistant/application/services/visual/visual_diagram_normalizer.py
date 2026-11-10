"""Filtra la evidencia visual conforme al alcance autorizado y a reglas Diagram."""

from __future__ import annotations

from typing import Any

from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    is_association,
    is_structural,
    translate_head_to_endpoints,
)
from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
)
from app.modules.assistant.domain.dialog.key_attribute_rules import (
    is_foreign_key_name,
    is_primary_key_name,
)



def normalize_visual_diagram(
    intent: VisualIntent, evidence: VisualEvidence
) -> dict[str, Any]:
    """Descarta llaves derivadas y aplica las exclusiones que devolvió intención."""
    scope = intent.scope
    class_scope = scope.get("classes", "all")
    attribute_scope = scope.get("attributes", "all")
    relation_scope = scope.get("relations", "all")
    classes: list[dict[str, Any]] = []
    derived_attributes: list[dict[str, str]] = []
    uncertainties = list(evidence.uncertainties)
    selected_relations = [
        dict(relation)
        for relation in evidence.relations
        if relation_scope != "none"
        and _relation_matches(
            relation_scope,
            str(relation.get("name") or "").casefold(),
            {
                str(relation.get("source") or "").casefold(),
                str(relation.get("target") or "").casefold(),
            },
        )
    ]
    for relation in selected_relations:
        rel_type = relation.get("relation_type", "ASSOCIATION")
        src = relation.get("source")
        tgt = relation.get("target")
        if not src or not tgt:
            uncertainties.append("Se detectó una relación visual con extremos incompletos o ilegibles.")
            continue
        if is_association(rel_type):
            src_card = relation.get("source_cardinality")
            tgt_card = relation.get("target_cardinality")
            if not src_card or not tgt_card:
                uncertainties.append(
                    f"La relación entre `{src}` y `{tgt}` no tiene cardinalidad legible; aclara sus cardinalidades antes de mutar."
                )
        elif is_structural(rel_type):
            head_class = relation.get("head_class")
            if not head_class or not isinstance(head_class, str):
                uncertainties.append(
                    f"No se pudo leer con certeza la dirección o cabeza de la relación `{rel_type}` entre `{src}` y `{tgt}`."
                )
            else:
                head_str = head_class.strip()
                src_str = str(src).strip()
                tgt_str = str(tgt).strip()
                if head_str.casefold() == src_str.casefold():
                    canonical_src, canonical_tgt = translate_head_to_endpoints(
                        rel_type, src_str, tgt_str, src_str
                    )
                    relation["source"] = canonical_src
                    relation["target"] = canonical_tgt
                elif head_str.casefold() == tgt_str.casefold():
                    canonical_src, canonical_tgt = translate_head_to_endpoints(
                        rel_type, src_str, tgt_str, tgt_str
                    )
                    relation["source"] = canonical_src
                    relation["target"] = canonical_tgt
                else:
                    uncertainties.append(
                        f"La cabeza `{head_str}` de la relación no coincide con ninguno de los dos extremos `{src}` y `{tgt}`."
                    )
    selected_class_names = {
        item["name"].strip().casefold()
        for item in evidence.classes
        if _selector_matches(class_scope, item["name"].strip())
    }
    relation_endpoint_names = {
        str(endpoint).strip().casefold()
        for relation in selected_relations
        for endpoint in (relation.get("source"), relation.get("target"))
        if isinstance(endpoint, str) and endpoint.strip()
    }
    for class_item in evidence.classes:
        class_name = class_item["name"].strip()
        folded_class_name = class_name.casefold()
        is_selected_class = folded_class_name in selected_class_names
        if not is_selected_class and folded_class_name not in relation_endpoint_names:
            continue
        attributes: list[dict[str, Any]] = []
        if is_selected_class and attribute_scope != "none":
            for attribute in class_item.get("attributes", []):
                name = attribute["name"].strip()
                key_kind = attribute.get("key_kind")
                # Algunos proveedores omiten el campo para un atributo ordinario.
                # Solo el nombre reservado `id` necesita clasificación explícita.
                if key_kind is None:
                    key_kind = "uncertain" if name.casefold() == "id" else "ordinary"
                # Solo un marcador visual explícito demuestra PK. El nombre `id`
                # por sí solo no es evidencia semántica, pero colisiona con la PK
                # generada por Diagram y requiere precisión antes de importarlo.
                if key_kind == "primary_key":
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": "primary_key_created_with_class"}
                    )
                    if name.casefold() != "id" or (
                        attribute.get("data_type") is not None
                        and attribute.get("data_type") != "UUID"
                    ):
                        uncertainties.append(
                            f"La clave primaria visual `{name}` de `{class_name}` no coincide claramente con la PK UUID generada por Diagram."
                        )
                    continue
                # Las FK explícitas son efectos de relación; jamás atributos secundarios.
                if key_kind == "foreign_key":
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": "foreign_key_created_with_relation"}
                    )
                    if relation_scope != "none" and not any(
                        str(relation.get("source", "")).casefold() == class_name.casefold()
                        or str(relation.get("target", "")).casefold() == class_name.casefold()
                        for relation in evidence.relations
                    ):
                        uncertainties.append(
                            f"La FK visual `{name}` de `{class_name}` no tiene una relación inequívoca asociada; no se materializará como atributo."
                        )
                    continue
                if key_kind == "uncertain":
                    reason = (
                        "reserved_key_name_requires_clarification"
                        if name.casefold() == "id"
                        else "key_kind_uncertain"
                    )
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": reason}
                    )
                    if name.casefold() == "id":
                        uncertainties.append(
                            f"Se observó un atributo llamado `id` sin marcador claro de PK; aclara si corresponde a la clave primaria existente."
                        )
                    else:
                        uncertainties.append(
                            f"no se pudo clasificar `{class_name}.{name}` como atributo ordinario o llave."
                        )
                    continue
                if is_primary_key_name(name, class_name):
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": "primary_key_created_with_class"}
                    )
                    continue
                if is_foreign_key_name(name, class_name):
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": "foreign_key_created_with_relation"}
                    )
                    continue
                if name.casefold() == "id":
                    derived_attributes.append(
                        {"class": class_name, "attribute": name, "reason": "reserved_key_name_requires_clarification"}
                    )
                    continue
                if not _selector_matches(attribute_scope, name):
                    continue
                normalized_attribute = dict(attribute)
                normalized_attribute["data_type"] = normalized_attribute.get(
                    "data_type"
                ) or _infer_data_type(name)
                nullable = normalized_attribute.get("nullable")
                normalized_attribute["nullable"] = (
                    nullable if isinstance(nullable, bool) else True
                )
                attributes.append(normalized_attribute)
        classes.append({**class_item, "name": class_name, "attributes": attributes})

    present_class_names = {item["name"].casefold() for item in classes}
    for endpoint_name in sorted(relation_endpoint_names - present_class_names):
        original_name = next(
            relation[field]
            for relation in selected_relations
            for field in ("source", "target")
            if isinstance(relation.get(field), str)
            and relation[field].strip().casefold() == endpoint_name
        )
        # A requested relation authorizes its named endpoint as a class, but not
        # that endpoint's unrequested attributes.
        classes.append({"name": original_name, "attributes": []})

    relations = selected_relations

    if any(item.get("reason") == "reserved_key_name_requires_clarification" for item in derived_attributes) and not any(
        "marcador claro de PK" in item for item in uncertainties
    ):
        uncertainties.append(
            "Se observó un atributo llamado `id` sin marcador claro de PK; aclara si corresponde a la clave primaria existente."
        )
    return {
        "supported": evidence.supported,
        "diagram_kind": evidence.diagram_kind,
        "needs_image": intent.needs_image,
        "scope": intent.scope,
        "classes": classes,
        "relations": relations,
        "derived_attributes": derived_attributes,
        "uncertainties": list(dict.fromkeys(uncertainties)),
    }


def _selector_matches(selector: Any, name: str) -> bool:
    if selector is None or selector == "all":
        return True
    if selector == "none":
        return False
    if isinstance(selector, list):
        return name.casefold() in {item.casefold() for item in selector if isinstance(item, str)}
    if isinstance(selector, dict):
        included = selector.get("include", "all")
        excluded = selector.get("exclude", "none")
        return _selector_matches(included, name) and not _selector_matches(excluded, name)
    # Invalid selectors fail closed.
    return False


def _relation_matches(
    selector: Any, relation_name: str, endpoint_names: set[str]
) -> bool:
    if selector is None or selector == "all":
        return True
    if selector == "none":
        return False
    if isinstance(selector, dict):
        included = selector.get("include", "all")
        excluded = selector.get("exclude", "none")
        return _relation_matches(included, relation_name, endpoint_names) and not _relation_matches(
            excluded, relation_name, endpoint_names
        )
    if isinstance(selector, list):
        selected = {item.casefold() for item in selector if isinstance(item, str)}
        return relation_name in selected or endpoint_names <= selected
    return False


def _infer_data_type(attribute_name: str) -> str | None:
    """Infer only conventional, high-confidence attribute names."""
    tokens = {
        token
        for token in attribute_name.casefold().replace("-", "_").split("_")
        if token
    }
    if tokens & {
        "nombre", "name", "title", "titulo", "descripcion", "description",
        "email", "correo", "direccion", "address", "codigo", "code",
    }:
        return "TEXT"
    if tokens & {"cantidad", "quantity", "count", "stock", "edad", "age"}:
        return "INTEGER"
    if tokens & {"precio", "price", "amount", "total", "costo", "cost", "saldo"}:
        return "DECIMAL"
    if tokens & {"activo", "active", "enabled", "verified", "validado", "is_active"}:
        return "BOOLEAN"
    return None
