"""Compuerta Pre-Flight de Validación de Metamodelo UML antes de Planificación."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Sequence

from app.modules.assistant.application.services.dialog.turn_signals import (
    extract_class_hints_from_key_request,
    is_isolated_fk_request,
    is_isolated_pk_request,
    normalize_text,
)

_AMBIGUOUS_RELATION_PATTERN = re.compile(
    r"^\s*(?:relaciona(?:r)?|conecta(?:r)?|haz\s+(?:una\s+)?relaci[oó]n|crea\s+(?:una\s+)?relaci[oó]n)(?:\s+(?:las\s+clases|clases))?\s*[.!]?$",
    re.IGNORECASE,
)

_CONCEPTUAL_QUESTION_PATTERN = re.compile(
    r"^(?:[¿?]|qu[eé]\s+es|c[oó]mo\s+funciona|para\s+qu[eé]\s+sirve|cu[aá]l\s+es|por\s+qu[eé])",
    re.IGNORECASE,
)


class MetamodelGateKind(StrEnum):
    ISOLATED_FK = "ISOLATED_FK"
    ISOLATED_PK = "ISOLATED_PK"
    AMBIGUOUS_RELATION = "AMBIGUOUS_RELATION"


@dataclass(frozen=True, slots=True)
class MetamodelGateDecision:
    kind: MetamodelGateKind
    explanation: str
    target_class: str | None = None
    related_class: str | None = None
    missing_fields: tuple[str, ...] = ()
    requires_input: bool = True


def is_conceptual_question(text: str) -> bool:
    norm = normalize_text(text)
    return bool(_CONCEPTUAL_QUESTION_PATTERN.search(norm))


def check_metamodel_gate(
    prompt: str,
    existing_classes: Sequence[str] = (),
) -> MetamodelGateDecision | None:
    """Evalúa de forma determinista si la orden viola invariantes del metamodelo UML."""
    clean = prompt.strip()
    if not clean:
        return None

    # Si es una consulta teórica o pregunta conceptual, no interceptar como violación
    if is_conceptual_question(clean):
        return None

    # 1. Petición de Llave Foránea aislada
    if is_isolated_fk_request(clean):
        target_cls, related_cls = extract_class_hints_from_key_request(clean)
        if target_cls and related_cls:
            explanation = (
                f"En los diagramas de clases UML, las llaves foráneas (FK) no se agregan manualmente como atributos. "
                f"Se generan automáticamente al crear la relación correspondiente entre las dos clases.\n\n"
                f"¿Deseas que relacione la clase **{target_cls}** con **{related_cls}**? "
                f"Por favor indícame qué tipo de relación deseas (por ejemplo: Asociación de 1 a N, Composición o Agregación)."
            )
            missing = ("tipo_relacion",)
        elif target_cls:
            explanation = (
                f"En los diagramas de clases UML, las llaves foráneas (FK) no se agregan manualmente como atributos. "
                f"Se generan automáticamente al crear la relación correspondiente entre las dos clases.\n\n"
                f"¿Con qué otra clase deseas relacionar **{target_cls}** para generar la llave foránea? "
                f"Por favor indica el nombre de la otra clase y el tipo de relación deseada."
            )
            missing = ("clase_destino", "tipo_relacion")
        else:
            explanation = (
                "En los diagramas de clases UML, las llaves foráneas (FK) no se agregan manualmente como atributos. "
                "Se generan automáticamente al crear la relación correspondiente entre las dos clases en el lienzo.\n\n"
                "¿Entre cuáles dos clases deseas crear la relación para generar la llave foránea y qué tipo de relación prefieres?"
            )
            missing = ("clase_origen", "clase_destino", "tipo_relacion")

        return MetamodelGateDecision(
            kind=MetamodelGateKind.ISOLATED_FK,
            explanation=explanation,
            target_class=target_cls,
            related_class=related_cls,
            missing_fields=missing,
            requires_input=True,
        )

    # 2. Petición de Llave Primaria aislada
    if is_isolated_pk_request(clean):
        target_cls, _ = extract_class_hints_from_key_request(clean)
        if target_cls:
            explanation = (
                f"En este modelador UML, cada clase cuenta automáticamente con su propia llave primaria (`id: UUID`), "
                f"por lo que no es necesario crearla de forma manual en la clase **{target_cls}**.\n\n"
                f"Si deseas agregar atributos descriptivos adicionales a **{target_cls}** (como fecha, total o código), "
                f"puedes indicármelo directamente."
            )
        else:
            explanation = (
                "En este modelador UML, cada clase cuenta automáticamente con su propia llave primaria (`id: UUID`), "
                "por lo que no es necesario crear llaves primarias de forma manual.\n\n"
                "Si deseas agregar atributos ordinarios a alguna clase, puedes indicarme el nombre de la clase y los atributos."
            )
        return MetamodelGateDecision(
            kind=MetamodelGateKind.ISOLATED_PK,
            explanation=explanation,
            target_class=target_cls,
            missing_fields=(),
            requires_input=False,
        )

    # 3. Petición de relación ambigua / sin extremos especificados
    if _AMBIGUOUS_RELATION_PATTERN.match(clean):
        classes_list = list(existing_classes)
        if len(classes_list) == 2:
            cls_a, cls_b = classes_list[0], classes_list[1]
            explanation = (
                f"He detectado dos clases en tu diagrama: **{cls_a}** y **{cls_b}**.\n\n"
                f"¿Deseas relacionar **{cls_a}** con **{cls_b}**? "
                f"Por favor indícame qué tipo de relación prefieres (por ejemplo: Asociación 1 a N, Agregación, Composición o Generalización)."
            )
            missing = ("confirmacion_extremos", "tipo_relacion")
        else:
            explanation = (
                "Para crear una relación necesito saber qué clases deseas conectar y el tipo de relación:\n\n"
                "- **Clases a conectar**: ¿Cuáles dos clases del diagrama deseas relacionar?\n"
                "- **Tipo de relación**: ¿Asociación (1 a N, 1 a 1), Agregación, Composición o Generalización?"
            )
            missing = ("clase_origen", "clase_destino", "tipo_relacion")

        return MetamodelGateDecision(
            kind=MetamodelGateKind.AMBIGUOUS_RELATION,
            explanation=explanation,
            missing_fields=missing,
            requires_input=True,
        )

    return None
