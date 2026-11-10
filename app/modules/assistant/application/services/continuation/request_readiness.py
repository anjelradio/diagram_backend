"""Evaluación de preparación de solicitudes conversacionales y reglas críticas/opcionales."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.assistant.application.services.planning.agent_intent import classify_agent_intent


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Informe de preparación de una solicitud para planificar o ejecutar."""

    is_ready: bool
    missing_fields: list[dict[str, Any]] = field(default_factory=list)
    resolved_facts: list[dict[str, Any]] = field(default_factory=list)
    grouped_question: str | None = None

    @property
    def missing_critical_fields(self) -> list[dict[str, Any]]:
        return [f for f in self.missing_fields if f.get("critical", False)]


class RequestReadiness:
    """Evalúa si una intención dispone de los datos indispensables antes de mutar."""

    def __init__(self, max_facts: int = 20, max_questions: int = 20) -> None:
        self.max_facts = max_facts
        self.max_questions = max_questions

    def evaluate_class_creation(
        self,
        *,
        name: str | None = None,
    ) -> ReadinessReport:
        """Exige el nombre de la clase; PK y demás valores técnicos usan defaults."""
        facts: list[dict[str, Any]] = []
        if name:
            facts.append({"key": "class.name", "value": name})
        missing = [] if name else [{
            "key": "class.name",
            "action": "CREATE_CLASS",
            "critical": True,
            "question": "¿Cómo se llama la clase?",
        }]
        return ReadinessReport(
            is_ready=not missing,
            missing_fields=missing,
            resolved_facts=facts,
            grouped_question=self.format_grouped_question(missing) if missing else None,
        )

    def evaluate_attribute_creation(
        self,
        *,
        target_class: str | None,
        name: str | None,
        data_type: str | None = None,
        nullable: bool | None = None,
    ) -> ReadinessReport:
        """Exige clase destino y nombre; el tipo infiere o null y nullable=True son opcionales."""
        missing: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []

        if target_class:
            facts.append({"key": "attribute.target_class", "value": target_class})
        else:
            missing.append(
                {
                    "key": "attribute.target_class",
                    "action": "CREATE_ATTRIBUTE",
                    "critical": True,
                    "question": f"¿En qué clase deseas agregar el atributo{f' `{name}`' if name else ''}?",
                }
            )

        if name:
            facts.append({"key": "attribute.name", "value": name})
        else:
            missing.append(
                {
                    "key": "attribute.name",
                    "action": "CREATE_ATTRIBUTE",
                    "critical": True,
                    "question": "¿Cuál es el nombre del atributo?",
                }
            )

        if data_type:
            facts.append({"key": "attribute.data_type", "value": data_type})
        if nullable is not None:
            facts.append({"key": "attribute.nullable", "value": nullable})

        critical_missing = [f for f in missing if f.get("critical", False)]
        is_ready = len(critical_missing) == 0
        grouped_q = self.format_grouped_question(missing) if not is_ready else None

        return ReadinessReport(
            is_ready=is_ready,
            missing_fields=missing[: self.max_questions],
            resolved_facts=facts[: self.max_facts],
            grouped_question=grouped_q,
        )

    def evaluate_relation(
        self,
        *,
        source_class: str | None,
        target_class: str | None,
        relation_type: str | None = None,
        source_cardinality: str | None = None,
        target_cardinality: str | None = None,
        generic_cardinality: str | None = None,
        whole_class: str | None = None,
        part_class: str | None = None,
        superclass: str | None = None,
        subclass: str | None = None,
        direction: str | None = None,
    ) -> ReadinessReport:
        """Aplica las reglas canónicas de la feature 041 para relaciones."""
        missing: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []

        if source_class:
            facts.append({"key": "relation.source_class", "value": source_class})
        else:
            missing.append(
                {
                    "key": "relation.source_class",
                    "action": "CREATE_RELATION",
                    "critical": True,
                    "question": "¿Cuál es la primera clase de la relación?",
                }
            )

        if target_class:
            facts.append({"key": "relation.target_class", "value": target_class})
        else:
            missing.append(
                {
                    "key": "relation.target_class",
                    "action": "CREATE_RELATION",
                    "critical": True,
                    "question": "¿Cuál es la segunda clase de la relación?",
                }
            )

        clean_type = (relation_type or "").upper()
        if clean_type:
            facts.append({"key": "relation.type", "value": clean_type})
        else:
            missing.append(
                {
                    "key": "relation.type",
                    "action": "CREATE_RELATION",
                    "critical": True,
                    "question": f"¿Qué tipo de relación deseas entre {source_class or 'las clases'} y {target_class or 'la otra'} (asociación, composición, agregación, herencia)?",
                }
            )

        # Reglas para ASSOCIATION
        if clean_type in ("ASSOCIATION", ""):
            if clean_type == "ASSOCIATION":
                if source_cardinality and target_cardinality:
                    facts.append({"key": "relation.source_cardinality", "value": source_cardinality})
                    facts.append({"key": "relation.target_cardinality", "value": target_cardinality})
                elif source_cardinality and not target_cardinality:
                    facts.append({"key": "relation.source_cardinality", "value": source_cardinality})
                    missing.append(
                        {
                            "key": "relation.target_cardinality",
                            "action": "CREATE_RELATION",
                            "critical": True,
                            "question": f"¿Cuál es la cardinalidad en el extremo de {target_class or 'la segunda clase'}?",
                        }
                    )
                elif target_cardinality and not source_cardinality:
                    facts.append({"key": "relation.target_cardinality", "value": target_cardinality})
                    missing.append(
                        {
                            "key": "relation.source_cardinality",
                            "action": "CREATE_RELATION",
                            "critical": True,
                            "question": f"¿Cuál es la cardinalidad en el extremo de {source_class or 'la primera clase'}?",
                        }
                    )
                elif generic_cardinality and not (source_cardinality and target_cardinality):
                    facts.append({"key": "relation.generic_cardinality", "value": generic_cardinality})
                    missing.append(
                        {
                            "key": "relation.endpoint_cardinalities",
                            "action": "CREATE_RELATION",
                            "critical": True,
                            "question": f"¿Qué cardinalidad corresponde a {source_class or 'un extremo'} y cuál a {target_class or 'el otro'}?",
                        }
                    )
                else:
                    missing.append(
                        {
                            "key": "relation.endpoint_cardinalities",
                            "action": "CREATE_RELATION",
                            "critical": True,
                            "question": f"¿Cuáles son las cardinalidades en cada extremo entre {source_class or 'la primera clase'} y {target_class or 'la segunda'}?",
                        }
                    )

        # Reglas para relaciones estructurales: prohíben cardinalidades, exigen dirección / roles
        elif clean_type in ("COMPOSITION", "AGGREGATION"):
            if whole_class and part_class:
                facts.append({"key": "relation.whole", "value": whole_class})
                facts.append({"key": "relation.part", "value": part_class})
            elif whole_class and not part_class:
                facts.append({"key": "relation.whole", "value": whole_class})
                missing.append(
                    {
                        "key": "relation.part",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la clase contenida (la parte) de {whole_class}?",
                    }
                )
            elif part_class and not whole_class:
                facts.append({"key": "relation.part", "value": part_class})
                missing.append(
                    {
                        "key": "relation.whole",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la clase contenedora (el todo) de {part_class}?",
                    }
                )
            elif direction:
                facts.append({"key": "relation.direction", "value": direction})
            else:
                missing.append(
                    {
                        "key": "relation.direction",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la clase contenedora (el todo) y cuál la contenida (la parte) entre {source_class or 'origen'} y {target_class or 'destino'}?",
                    }
                )

        elif clean_type == "GENERALIZATION":
            eff_super = superclass or whole_class
            eff_sub = subclass or part_class
            if eff_super and eff_sub:
                facts.append({"key": "relation.superclass", "value": eff_super})
                facts.append({"key": "relation.subclass", "value": eff_sub})
            elif eff_super and not eff_sub:
                facts.append({"key": "relation.superclass", "value": eff_super})
                missing.append(
                    {
                        "key": "relation.subclass",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la clase hija (subclase) de {eff_super}?",
                    }
                )
            elif eff_sub and not eff_super:
                facts.append({"key": "relation.subclass", "value": eff_sub})
                missing.append(
                    {
                        "key": "relation.superclass",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la superclase (padre) de {eff_sub}?",
                    }
                )
            elif direction:
                facts.append({"key": "relation.direction", "value": direction})
            else:
                missing.append(
                    {
                        "key": "relation.direction",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la superclase (padre) y cuál la subclase (hija) entre {source_class or 'origen'} y {target_class or 'destino'}?",
                    }
                )

        elif clean_type in ("REALIZATION", "DEPENDENCY"):
            if direction:
                facts.append({"key": "relation.direction", "value": direction})
            else:
                missing.append(
                    {
                        "key": "relation.direction",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": f"¿Cuál es la dirección de la relación entre {source_class or 'origen'} y {target_class or 'destino'}?",
                    }
                )

        critical_missing = [f for f in missing if f.get("critical", False)]
        is_ready = len(critical_missing) == 0
        grouped_q = self.format_grouped_question(missing) if not is_ready else None

        return ReadinessReport(
            is_ready=is_ready,
            missing_fields=missing[: self.max_questions],
            resolved_facts=facts[: self.max_facts],
            grouped_question=grouped_q,
        )

    def format_grouped_question(self, missing_fields: list[dict[str, Any]]) -> str:
        """Agrupa las preguntas de los campos críticos en una redacción cordial."""
        critical = [f for f in missing_fields if f.get("critical", False)]
        if not critical:
            return ""
        if len(critical) == 1:
            return str(critical[0]["question"])

        questions = [str(f["question"]).strip() for f in critical]
        return " Para continuar, indícame: " + " Además, ".join(questions)

    def merge_facts(
        self,
        existing_facts: list[dict[str, Any]],
        new_facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Combina hechos preservando procedencia e imponiendo límite de 20."""
        facts_map: dict[str, dict[str, Any]] = {}
        for f in existing_facts:
            if isinstance(f, dict) and "key" in f:
                facts_map[f["key"]] = dict(f)
        for nf in new_facts:
            if isinstance(nf, dict) and "key" in nf:
                facts_map[nf["key"]] = dict(nf)
        merged = list(facts_map.values())
        return merged[: self.max_facts]

    def compute_remaining_missing(
        self,
        candidate_missing: list[dict[str, Any]],
        resolved_facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Calcula los campos críticos restantes eliminando los ya resueltos."""
        resolved_keys = {
            f.get("key") for f in resolved_facts
            if isinstance(f, dict) and "key" in f
        }
        if "relation.source_cardinality" in resolved_keys and "relation.target_cardinality" in resolved_keys:
            resolved_keys.add("relation.endpoint_cardinalities")
        if "relation.superclass" in resolved_keys and "relation.subclass" in resolved_keys:
            resolved_keys.add("relation.direction")
        if "relation.whole" in resolved_keys and "relation.part" in resolved_keys:
            resolved_keys.add("relation.direction")

        remaining: list[dict[str, Any]] = []
        for f in candidate_missing:
            if not isinstance(f, dict):
                continue
            k = f.get("key")
            if not k or k in resolved_keys:
                continue
            if k == "relation.endpoint_cardinalities":
                if "relation.source_cardinality" in resolved_keys and "relation.target_cardinality" not in resolved_keys:
                    remaining.append({
                        "key": "relation.target_cardinality",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": "¿Cuál es la cardinalidad en el extremo destino?",
                    })
                    continue
                elif "relation.target_cardinality" in resolved_keys and "relation.source_cardinality" not in resolved_keys:
                    remaining.append({
                        "key": "relation.source_cardinality",
                        "action": "CREATE_RELATION",
                        "critical": True,
                        "question": "¿Cuál es la cardinalidad en el extremo origen?",
                    })
                    continue
            remaining.append(f)
        return remaining

    def evaluate_initial_request(self, prompt: str) -> ReadinessReport | None:
        """Examina si una nueva solicitud de mutación adolece de campos críticos."""
        import re

        clean = prompt.strip()

        # 1. Detección de creación de relación
        rel_match = re.search(
            r"\b(?:relaciona(?:r)?|relacion(?:es)?|conecta(?:r)?|(?:crea(?:r)?|crees|haz|haga(?:s)?|hacer)\s+(?:una\s+)?relaci[oó]n|crea(?:r)?\s+(?:una\s+)?(?:asociaci[oó]n|composici[oó]n|agregaci[oó]n|herencia))\b",
            clean,
            re.IGNORECASE,
        )
        if rel_match and classify_agent_intent(clean).requires_mutation:
            # Extracción de extremos
            source: str | None = None
            target: str | None = None

            m_pair = re.search(
                r"(?:entre|relaci[oó]n\s+con)\s+(?:(?:la\s+)?clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+y\s+(?:(?:la\s+)?clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                clean,
                re.IGNORECASE,
            )
            if m_pair:
                source, target = m_pair.group(1), m_pair.group(2)
            else:
                m_con = re.search(
                    r"(?:relaciona(?:r)?|conecta(?:r)?)\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+con\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                    clean,
                    re.IGNORECASE,
                )
                if m_con:
                    source, target = m_con.group(1), m_con.group(2)
                else:
                    # «crea una clase X y relaciónala con Y» y variantes
                    # coloquiales como «quiero que las relaciones con Y».
                    m_created = re.search(
                        r"\bclase\s+(?:llamada\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                        clean,
                        re.IGNORECASE,
                    )
                    m_target = re.search(
                        r"\b(?:relaciona(?:r)?|relacion(?:es)?|conecta(?:r)?)\b[^.]*?\bcon\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                        clean,
                        re.IGNORECASE,
                    )
                    if m_created and m_target:
                        source, target = m_created.group(1), m_target.group(1)

            # Detección de tipo
            rel_type: str | None = None
            if re.search(r"\bcomposici[oó]n\b", clean, re.IGNORECASE):
                rel_type = "COMPOSITION"
            elif re.search(r"\bagregaci[oó]n\b", clean, re.IGNORECASE):
                rel_type = "AGGREGATION"
            elif re.search(r"\b(?:herencia|generalizaci[oó]n)\b", clean, re.IGNORECASE):
                rel_type = "GENERALIZATION"
            elif re.search(r"\brealizaci[oó]n\b", clean, re.IGNORECASE):
                rel_type = "REALIZATION"
            elif re.search(r"\bdependencia\b", clean, re.IGNORECASE):
                rel_type = "DEPENDENCY"
            elif re.search(r"\basociaci[oó]n\b", clean, re.IGNORECASE):
                rel_type = "ASSOCIATION"

            # Roles direccionales
            whole_class = None
            part_class = None
            m_contains = re.search(
                r"([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+contiene\s+a\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                clean,
                re.IGNORECASE,
            )
            if m_contains:
                whole_class, part_class = m_contains.group(1), m_contains.group(2)

            report = self.evaluate_relation(
                source_class=source,
                target_class=target,
                relation_type=rel_type,
                whole_class=whole_class,
                part_class=part_class,
            )
            if not report.is_ready:
                return report

        # 2. Detección de creación de atributo
        attr_match = re.search(
            r"\b(?:crea(?:r)?|agrega(?:r)?|a[ñn]ade(?:r)?)\s+(?:un\s+)?atributo(?:\s+llamado)?\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)?",
            clean,
            re.IGNORECASE,
        )
        if attr_match:
            name = attr_match.group(1)
            target_class = None
            m_cls = re.search(r"(?:en|para)\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)", clean, re.IGNORECASE)
            if m_cls:
                target_class = m_cls.group(1)
            report = self.evaluate_attribute_creation(target_class=target_class, name=name)
            if not report.is_ready:
                return report

        # 3. Detección de creación de clase
        cls_match = re.search(
            r"\b(?:crea(?:r)?|agrega(?:r)?)\s+(?:una\s+)?clase(?:\s+llamada)?\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)?",
            clean,
            re.IGNORECASE,
        )
        if cls_match:
            name = cls_match.group(1)
            return self.evaluate_class_creation(name=name)

        return None

