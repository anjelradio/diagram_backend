"""Servicio de resolución de vacíos e inferencia semántica para diagramas visuales.

Fase de Gap Resolution / Enriquecimiento Semántico:
1. Ignora y descarta atributos ID, PK y FK visuales (se autogeneran en clases y relaciones).
2. Normaliza tipos de datos de atributos hacia DiagramAttributeDataType (infiere o asigna None/null).
3. Expande clases conectadas con sus atributos cuando se solicita 'clase y sus relaciones'.
4. Deduce y resuelve cardinalidades y direcciones faltantes en relaciones (incluyendo recursivas y N:M).
5. Prunea incertidumbres resueltas autónomamente para no bloquear la mutación.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any

from app.modules.assistant.application.ports.providers.ai_provider import AiProvider
from app.modules.assistant.application.services.diagram.agent_relation_policy import (
    is_association,
    is_structural,
    translate_head_to_endpoints,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.visual.visual_contracts import (
    DiagramAttributeDataType,
    DiagramRelationType,
    VisualEvidence,
    VisualIntent,
    _canonical_data_type,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    _infer_data_type,
)
from app.modules.assistant.domain.dialog.key_attribute_rules import (
    is_any_key_name,
    is_foreign_key_name,
    is_primary_key_name,
)

logger = logging.getLogger(__name__)

_CONNECTED_REQUEST_PATTERNS = (
    re.compile(r"\b(y|con)\s+(sus\s+|las\s+)?relaciones\b", re.IGNORECASE),
    re.compile(r"\btodo\s+lo\s+(que\s+se\s+conecta|relacionado)\b", re.IGNORECASE),
    re.compile(r"\bconectad[ao]s?\b", re.IGNORECASE),
    re.compile(r"\brelacionad[ao]s?\b", re.IGNORECASE),
)

_EXPANDED_DATA_TYPE_MAP: dict[str, str] = {
    "VARCHAR": "TEXT",
    "NVARCHAR": "TEXT",
    "CHAR": "TEXT",
    "STRING": "TEXT",
    "TEXT": "TEXT",
    "STR": "TEXT",
    "CHARACTER": "TEXT",
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "INT2": "INTEGER",
    "INT4": "INTEGER",
    "INT8": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
    "SERIAL": "INTEGER",
    "BIGSERIAL": "INTEGER",
    "FLOAT": "DECIMAL",
    "DOUBLE": "DECIMAL",
    "REAL": "DECIMAL",
    "DECIMAL": "DECIMAL",
    "NUMERIC": "DECIMAL",
    "MONEY": "DECIMAL",
    "NUMBER": "DECIMAL",
    "BOOL": "BOOLEAN",
    "BOOLEAN": "BOOLEAN",
    "BIT": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMPTZ": "TIMESTAMP",
    "TIME": "TIMESTAMP",
    "UUID": "UUID",
    "GUID": "UUID",
}

_PARENT_SEMANTIC_STEMS = {
    "categoria", "category", "usuario", "user", "cliente", "customer",
    "empresa", "company", "departamento", "department", "pais", "country",
    "ciudad", "city", "rol", "role", "autor", "author", "padre", "parent",
    "venta", "factura", "orden", "order", "pedido",
}

_CHILD_SEMANTIC_STEMS = {
    "producto", "product", "pedido", "order", "venta", "sale",
    "detalle", "detail", "item", "empleado", "employee", "libro", "book",
    "factura", "invoice", "linea", "hijo", "child", "pago", "payment",
}

_RESOLVED_UNCERTAINTY_FRAGMENTS = (
    "tipos admitidos",
    "tipo de un atributo",
    "marcador claro de pk",
    "clave primaria visual",
    "pk uuid",
    "fk visual",
    "no tiene una relación inequívoca asociada",
    "no se pudo clasificar",
)


class VisualGapResolver:
    """Resuelve vacíos e incertidumbres semánticas en la evidencia visual."""

    def __init__(
        self,
        ai_provider: AiProvider | None = None,
        prompt_composer: PromptComposer | None = None,
    ) -> None:
        self.ai_provider = ai_provider
        self.prompt_composer = prompt_composer

    async def resolve(
        self,
        *,
        prompt: str,
        intent: VisualIntent,
        evidence: VisualEvidence,
        normalized_evidence: dict[str, Any],
    ) -> tuple[VisualIntent, dict[str, Any]]:
        """Procesa y enriquece la evidencia normalizada resolviendo vacíos."""
        classes = [dict(c) for c in normalized_evidence.get("classes", [])]
        relations = [dict(r) for r in normalized_evidence.get("relations", [])]
        derived_attributes = list(normalized_evidence.get("derived_attributes", []))
        uncertainties = list(normalized_evidence.get("uncertainties", []))

        # 1. Detectar si el usuario pide expandir clases conectadas ("Producto y sus relaciones")
        expand_connected = self._should_expand_connected(prompt, intent)
        raw_classes_by_name = {
            c["name"].strip().casefold(): c
            for c in getattr(evidence, "classes", ())
            if isinstance(c, dict) and "name" in c
        }

        if expand_connected:
            classes, relations = self._expand_connected_entities(
                current_classes=classes,
                current_relations=relations,
                raw_evidence_classes=raw_classes_by_name,
                raw_evidence_relations=getattr(evidence, "relations", ()),
            )

        # 2. Filtrar atributos ID, PK y FK en todas las clases a crear y normalizar tipos
        cleaned_classes: list[dict[str, Any]] = []
        derived_by_class: dict[str, list[dict[str, str]]] = {}

        for class_item in classes:
            c_name = class_item["name"].strip()
            c_folded = c_name.casefold()
            kept_attributes: list[dict[str, Any]] = []

            for attr in class_item.get("attributes", []):
                attr_name = attr.get("name", "").strip()
                if not attr_name:
                    continue

                if self._is_id_or_fk_attribute(attr_name, c_name, attr.get("key_kind")):
                    derived_entry = {
                        "class": c_name,
                        "attribute": attr_name,
                        "reason": (
                            "primary_key_created_with_class"
                            if is_primary_key_name(attr_name, c_name)
                            else "foreign_key_created_with_relation"
                        ),
                    }
                    derived_attributes.append(derived_entry)
                    derived_by_class.setdefault(c_folded, []).append(derived_entry)
                    continue

                # Normalizar tipo de dato
                normalized_attr = dict(attr)
                normalized_attr["name"] = attr_name
                normalized_attr["data_type"] = self._canonicalize_data_type(
                    attr.get("data_type"), attr_name
                )
                if "nullable" not in normalized_attr or normalized_attr["nullable"] is None:
                    normalized_attr["nullable"] = True
                kept_attributes.append(normalized_attr)

            cleaned_classes.append({
                **class_item,
                "name": c_name,
                "attributes": kept_attributes,
            })

        # 3. Resolver vacíos en relaciones (cardinalidades, tipos y dirección)
        resolved_relations: list[dict[str, Any]] = []
        for rel in relations:
            resolved_rel = self._resolve_relation_gaps(
                dict(rel),
                derived_by_class=derived_by_class,
            )
            if resolved_rel is not None:
                resolved_relations.append(resolved_rel)

        # 4. Prunear incertidumbres que han sido resueltas autónomamente
        scope_relations = intent.scope.get("relations", "all") if isinstance(intent.scope, dict) else "all"
        cleaned_uncertainties = self._prune_resolved_uncertainties(
            uncertainties,
            resolved_relations,
            scope_relations=scope_relations,
        )

        logger.info(
            "[Fase 3 · Visión] Resolución de vacíos completada: clases=%d, relaciones=%d, "
            "incertidumbres_restantes=%d (expand_connected=%s)",
            len(cleaned_classes),
            len(resolved_relations),
            len(cleaned_uncertainties),
            expand_connected,
        )

        # 5. Si se expandieron entidades conectadas, actualizar el scope del intent para que el planificador esté alineado
        resolved_intent = intent
        if expand_connected and cleaned_classes:
            new_scope = dict(intent.scope)
            new_scope["classes"] = [c["name"] for c in cleaned_classes]
            new_scope["relations"] = "all"
            resolved_intent = replace(intent, scope=new_scope)

        resolved_payload = {
            "supported": normalized_evidence.get("supported", True),
            "diagram_kind": normalized_evidence.get("diagram_kind", "ERD"),
            "needs_image": normalized_evidence.get("needs_image", True),
            "scope": normalized_evidence.get("scope", {}),
            "classes": cleaned_classes,
            "relations": resolved_relations,
            "derived_attributes": derived_attributes,
            "uncertainties": cleaned_uncertainties,
        }

        return resolved_intent, resolved_payload

    @staticmethod
    def _should_expand_connected(prompt: str, intent: VisualIntent) -> bool:
        """Determina si la solicitud exige conectar clases vecinas con sus atributos."""
        prompt_lower = (prompt or "").lower()
        if any(p.search(prompt_lower) for p in _CONNECTED_REQUEST_PATTERNS):
            return True
        scope = getattr(intent, "scope", {}) or {}
        if scope.get("expand_connected_classes") is True:
            return True
        # Si se solicita una sola clase pero relaciones != 'none'
        classes_scope = scope.get("classes")
        relations_scope = scope.get("relations")
        if (
            isinstance(classes_scope, list)
            and len(classes_scope) == 1
            and relations_scope not in (None, "none")
        ):
            return True
        return False

    def _expand_connected_entities(
        self,
        *,
        current_classes: list[dict[str, Any]],
        current_relations: list[dict[str, Any]],
        raw_evidence_classes: dict[str, dict[str, Any]],
        raw_evidence_relations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Expande las clases conectadas y sus atributos completos."""
        expanded_classes_map: dict[str, dict[str, Any]] = {
            c["name"].strip().casefold(): dict(c) for c in current_classes
        }
        expanded_relations: list[dict[str, Any]] = list(current_relations)

        # Buscar todas las relaciones de evidencia que involucren a las clases iniciales
        for rel in raw_evidence_relations:
            if not isinstance(rel, dict):
                continue
            src = str(rel.get("source", "")).strip()
            tgt = str(rel.get("target", "")).strip()
            if not src or not tgt:
                continue

            src_folded = src.casefold()
            tgt_folded = tgt.casefold()

            src_in_scope = src_folded in expanded_classes_map
            tgt_in_scope = tgt_folded in expanded_classes_map

            if src_in_scope or tgt_in_scope:
                # Incluir la relación si no está ya
                rel_dict = dict(rel)
                rel_endpoints = {src_folded, tgt_folded}
                rel_type = rel_dict.get("relation_type")
                if not any(
                    {str(r.get("source", "")).strip().casefold(), str(r.get("target", "")).strip().casefold()} == rel_endpoints
                    and r.get("relation_type") == rel_type
                    for r in expanded_relations
                ):
                    expanded_relations.append(rel_dict)

                # Asegurar que ambos extremos existan con sus atributos de la evidencia cruda
                for endpoint_str, endpoint_folded in ((src, src_folded), (tgt, tgt_folded)):
                    if endpoint_folded not in expanded_classes_map:
                        raw_c = raw_evidence_classes.get(endpoint_folded)
                        if raw_c:
                            expanded_classes_map[endpoint_folded] = {
                                "name": raw_c.get("name", endpoint_str),
                                "attributes": list(raw_c.get("attributes", [])),
                            }
                        else:
                            expanded_classes_map[endpoint_folded] = {
                                "name": endpoint_str,
                                "attributes": [],
                            }
                    elif not expanded_classes_map[endpoint_folded].get("attributes"):
                        raw_c = raw_evidence_classes.get(endpoint_folded)
                        if raw_c and raw_c.get("attributes"):
                            expanded_classes_map[endpoint_folded]["attributes"] = list(
                                raw_c["attributes"]
                            )

        return list(expanded_classes_map.values()), expanded_relations

    @staticmethod
    def _is_id_or_fk_attribute(
        name: str,
        class_name: str | None = None,
        key_kind: str | None = None,
    ) -> bool:
        """Comprueba si un nombre de atributo debe ignorarse por ser llave (PK o FK)."""
        if key_kind in ("primary_key", "foreign_key"):
            return True
        clean = name.strip().lower()
        if not clean:
            return False
        if clean in {"id", "pk", "uuid", "guid", "id_pk", "fk"}:
            return True
        if is_any_key_name(name, class_name):
            return True
        if clean.startswith("id_") or clean.endswith("_id") or clean.startswith("fk_") or clean.endswith("_fk"):
            return True
        return False

    @staticmethod
    def _canonicalize_data_type(raw_type: Any, attr_name: str) -> str | None:
        """Normaliza tipos de datos o infiere por semántica; si duda, retorna None."""
        if isinstance(raw_type, str):
            clean_type = raw_type.strip().upper()
            clean_type = re.sub(r"\(.*\)", "", clean_type).strip()
            if clean_type in _EXPANDED_DATA_TYPE_MAP:
                return _EXPANDED_DATA_TYPE_MAP[clean_type]
            canon = _canonical_data_type(clean_type)
            if canon:
                return canon

        # Inferencia por nombre convencional
        inferred = _infer_data_type(attr_name)
        if inferred:
            return inferred

        tokens = {
            token
            for token in attr_name.casefold().replace("-", "_").split("_")
            if token
        }
        if tokens & {"fecha", "date", "birthdate", "nacimiento", "plazo", "vencimiento"}:
            return "DATE"
        if tokens & {"created", "updated", "creado", "actualizado", "timestamp", "datetime"}:
            return "TIMESTAMP"

        return None

    @staticmethod
    def _resolve_relation_gaps(
        rel: dict[str, Any],
        derived_by_class: dict[str, list[dict[str, str]]],
    ) -> dict[str, Any] | None:
        """Deduce cardinalidades, tipos y dirección cuando no vienen legibles."""
        src = str(rel.get("source", "")).strip()
        tgt = str(rel.get("target", "")).strip()
        if not src or not tgt:
            return rel

        src_folded = src.casefold()
        tgt_folded = tgt.casefold()

        raw_rel_type = rel.get("relation_type")
        if not raw_rel_type or raw_rel_type not in {item.value for item in DiagramRelationType}:
            rel["relation_type"] = DiagramRelationType.ASSOCIATION.value
        rel_type = rel["relation_type"]

        # Caso A: Relación Reflexiva / Recursiva
        if src_folded == tgt_folded:
            rel["relation_type"] = DiagramRelationType.ASSOCIATION.value
            rel["source_cardinality"] = rel.get("source_cardinality") or "0..1"
            rel["target_cardinality"] = rel.get("target_cardinality") or "0..*"
            return rel

        # Caso B: Asociación
        if is_association(rel_type):
            src_card = rel.get("source_cardinality")
            tgt_card = rel.get("target_cardinality")

            if not src_card or not tgt_card:
                # Comprobar si source contenía una FK derivada hacia target
                src_derived = derived_by_class.get(src_folded, [])
                has_fk_to_tgt = any(tgt_folded in item.get("attribute", "").casefold() for item in src_derived)

                tgt_derived = derived_by_class.get(tgt_folded, [])
                has_fk_to_src = any(src_folded in item.get("attribute", "").casefold() for item in tgt_derived)

                if has_fk_to_tgt and not has_fk_to_src:
                    rel["source_cardinality"] = src_card or "0..*"
                    rel["target_cardinality"] = tgt_card or "1"
                elif has_fk_to_src and not has_fk_to_tgt:
                    rel["source_cardinality"] = src_card or "1"
                    rel["target_cardinality"] = tgt_card or "0..*"
                else:
                    # Inferencia por jerarquía semántica
                    src_is_parent = any(s in src_folded for s in _PARENT_SEMANTIC_STEMS)
                    tgt_is_parent = any(s in tgt_folded for s in _PARENT_SEMANTIC_STEMS)
                    src_is_child = any(s in src_folded for s in _CHILD_SEMANTIC_STEMS)
                    tgt_is_child = any(s in tgt_folded for s in _CHILD_SEMANTIC_STEMS)

                    if src_is_parent and tgt_is_child:
                        rel["source_cardinality"] = src_card or "1"
                        rel["target_cardinality"] = tgt_card or "0..*"
                    elif tgt_is_parent and src_is_child:
                        rel["source_cardinality"] = src_card or "0..*"
                        rel["target_cardinality"] = tgt_card or "1"

            return rel

        # Caso C: Relación Estructural (Composición, Agregación, Generalización, etc.)
        if is_structural(rel_type):
            head = rel.get("head_class")
            if not head or not isinstance(head, str) or head.strip() not in (src, tgt):
                if rel_type in (DiagramRelationType.AGGREGATION.value, DiagramRelationType.COMPOSITION.value):
                    head = src  # El contenedor es la cabeza
                elif rel_type in (DiagramRelationType.GENERALIZATION.value, DiagramRelationType.REALIZATION.value):
                    head = tgt  # La superclase/contrato es la cabeza
                else:
                    head = tgt
                rel["head_class"] = head

            try:
                canonical_src, canonical_tgt = translate_head_to_endpoints(
                    rel_type, src, tgt, rel["head_class"]
                )
                rel["source"] = canonical_src
                rel["target"] = canonical_tgt
            except Exception:
                pass
            rel["source_cardinality"] = None
            rel["target_cardinality"] = None
            return rel

        return rel

    @staticmethod
    def _prune_resolved_uncertainties(
        uncertainties: list[str],
        resolved_relations: list[dict[str, Any]],
        scope_relations: Any = "all",
    ) -> list[str]:
        """Elimina de la lista de incertidumbres aquellas que fueron resueltas."""
        if scope_relations == "none":
            any_relation_missing_cardinality = False
            any_structural_missing_head = False
        else:
            any_relation_missing_cardinality = any(
                not (r.get("source_cardinality") and r.get("target_cardinality"))
                for r in resolved_relations
                if is_association(r.get("relation_type"))
            ) or not resolved_relations

            any_structural_missing_head = any(
                not r.get("head_class")
                for r in resolved_relations
                if is_structural(r.get("relation_type"))
            )

        cleaned: list[str] = []
        for u in uncertainties:
            u_lower = u.lower()

            if "cardinalidad" in u_lower:
                mentioned_relations = [
                    r for r in resolved_relations
                    if r.get("source", "").casefold() in u_lower
                    and r.get("target", "").casefold() in u_lower
                ]
                if mentioned_relations:
                    if any(
                        not (r.get("source_cardinality") and r.get("target_cardinality"))
                        for r in mentioned_relations
                    ):
                        cleaned.append(u)
                    continue
                else:
                    if any_relation_missing_cardinality:
                        cleaned.append(u)
                    continue

            if "dirección o cabeza" in u_lower or "cabeza de la relación" in u_lower:
                mentioned_structural = [
                    r for r in resolved_relations
                    if r.get("source", "").casefold() in u_lower
                    and r.get("target", "").casefold() in u_lower
                ]
                if mentioned_structural:
                    if any(not r.get("head_class") for r in mentioned_structural):
                        cleaned.append(u)
                    continue
                else:
                    if any_structural_missing_head:
                        cleaned.append(u)
                    continue

            if any(fragment in u_lower for fragment in _RESOLVED_UNCERTAINTY_FRAGMENTS):
                continue

            cleaned.append(u)
        return cleaned
