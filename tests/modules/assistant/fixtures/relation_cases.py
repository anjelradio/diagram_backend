"""Fixtures canónicas de casos de relaciones para pruebas del asistente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.diagram.domain.enums.diagram_cardinality import DiagramCardinality
from app.modules.diagram.domain.enums.diagram_relation_type import DiagramRelationType

CANONICAL_CARDINALITIES: tuple[str, ...] = ("1", "0..1", "0..*", "1..*")

# Todas las 16 combinaciones ordenadas de cardinalidad para asociaciones
ASSOCIATION_CARDINALITY_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (src, tgt) for src in CANONICAL_CARDINALITIES for tgt in CANONICAL_CARDINALITIES
)

CARDINALITY_ALIASES: dict[str, str] = {
    "1..1": "1",
}


@dataclass(frozen=True, slots=True)
class RelationSemanticRoleCase:
    relation_type: DiagramRelationType
    source_role: str
    target_role: str
    head_endpoint: str | None  # "source" | "target" | None
    visual_head_symbol: str


RELATION_SEMANTIC_ROLE_CASES: dict[DiagramRelationType, RelationSemanticRoleCase] = {
    DiagramRelationType.ASSOCIATION: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.ASSOCIATION,
        source_role="source_cardinality_endpoint",
        target_role="target_cardinality_endpoint",
        head_endpoint=None,
        visual_head_symbol="none",
    ),
    DiagramRelationType.AGGREGATION: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.AGGREGATION,
        source_role="whole",
        target_role="part",
        head_endpoint="source",
        visual_head_symbol="empty_diamond",
    ),
    DiagramRelationType.COMPOSITION: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.COMPOSITION,
        source_role="whole",
        target_role="part",
        head_endpoint="source",
        visual_head_symbol="filled_diamond",
    ),
    DiagramRelationType.GENERALIZATION: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.GENERALIZATION,
        source_role="subclass",
        target_role="superclass",
        head_endpoint="target",
        visual_head_symbol="triangle",
    ),
    DiagramRelationType.REALIZATION: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.REALIZATION,
        source_role="implementer",
        target_role="contract",
        head_endpoint="target",
        visual_head_symbol="triangle",
    ),
    DiagramRelationType.DEPENDENCY: RelationSemanticRoleCase(
        relation_type=DiagramRelationType.DEPENDENCY,
        source_role="dependent",
        target_role="dependency",
        head_endpoint="target",
        visual_head_symbol="arrow",
    ),
}


@dataclass(frozen=True, slots=True)
class StructuralPhraseCase:
    phrase: str
    relation_type: DiagramRelationType
    expected_source_class: str
    expected_target_class: str


STRUCTURAL_PHRASE_CASES: tuple[StructuralPhraseCase, ...] = (
    StructuralPhraseCase(
        phrase="Animal se compone de Corazón",
        relation_type=DiagramRelationType.COMPOSITION,
        expected_source_class="Animal",
        expected_target_class="Corazón",
    ),
    StructuralPhraseCase(
        phrase="Equipo agrega Jugador",
        relation_type=DiagramRelationType.AGGREGATION,
        expected_source_class="Equipo",
        expected_target_class="Jugador",
    ),
    StructuralPhraseCase(
        phrase="Caballo hereda de Animal",
        relation_type=DiagramRelationType.GENERALIZATION,
        expected_source_class="Caballo",
        expected_target_class="Animal",
    ),
    StructuralPhraseCase(
        phrase="Servicio implementa Contrato",
        relation_type=DiagramRelationType.REALIZATION,
        expected_source_class="Servicio",
        expected_target_class="Contrato",
    ),
    StructuralPhraseCase(
        phrase="Pedido depende de Inventario",
        relation_type=DiagramRelationType.DEPENDENCY,
        expected_source_class="Pedido",
        expected_target_class="Inventario",
    ),
)


@dataclass(frozen=True, slots=True)
class ExplicitHeadCase:
    phrase: str
    relation_type: DiagramRelationType
    head_class: str
    other_class: str
    expected_source_class: str
    expected_target_class: str


EXPLICIT_HEAD_CASES: tuple[ExplicitHeadCase, ...] = (
    ExplicitHeadCase(
        phrase="La cabeza de composición está en Casa y conecta Habitación",
        relation_type=DiagramRelationType.COMPOSITION,
        head_class="Casa",
        other_class="Habitación",
        expected_source_class="Casa",
        expected_target_class="Habitación",
    ),
    ExplicitHeadCase(
        phrase="La cabeza de agregación está en Empresa y conecta Departamento",
        relation_type=DiagramRelationType.AGGREGATION,
        head_class="Empresa",
        other_class="Departamento",
        expected_source_class="Empresa",
        expected_target_class="Departamento",
    ),
    ExplicitHeadCase(
        phrase="La cabeza de herencia está en Animal y conecta Caballo",
        relation_type=DiagramRelationType.GENERALIZATION,
        head_class="Animal",
        other_class="Caballo",
        expected_source_class="Caballo",
        expected_target_class="Animal",
    ),
    ExplicitHeadCase(
        phrase="La cabeza de realización está en IRepositorio y conecta SqlRepositorio",
        relation_type=DiagramRelationType.REALIZATION,
        head_class="IRepositorio",
        other_class="SqlRepositorio",
        expected_source_class="SqlRepositorio",
        expected_target_class="IRepositorio",
    ),
    ExplicitHeadCase(
        phrase="La cabeza de dependencia está en AuthProvider y conecta LoginService",
        relation_type=DiagramRelationType.DEPENDENCY,
        head_class="AuthProvider",
        other_class="LoginService",
        expected_source_class="LoginService",
        expected_target_class="AuthProvider",
    ),
)


@dataclass(frozen=True, slots=True)
class AssociationEquivalenceCase:
    source_class: str
    target_class: str
    source_cardinality: str
    target_cardinality: str
    name: str
    candidate_source_class: str
    candidate_target_class: str
    candidate_source_cardinality: str
    candidate_target_cardinality: str
    candidate_name: str
    is_equivalent: bool


ASSOCIATION_EQUIVALENCE_CASES: tuple[AssociationEquivalenceCase, ...] = (
    # Direct match
    AssociationEquivalenceCase(
        source_class="Pedido",
        target_class="Producto",
        source_cardinality="1",
        target_cardinality="0..*",
        name="contiene",
        candidate_source_class="Pedido",
        candidate_target_class="Producto",
        candidate_source_cardinality="1",
        candidate_target_cardinality="0..*",
        candidate_name="contiene",
        is_equivalent=True,
    ),
    # Reversed with swapped cardinalities -> equivalent
    AssociationEquivalenceCase(
        source_class="Pedido",
        target_class="Producto",
        source_cardinality="1",
        target_cardinality="0..*",
        name="contiene",
        candidate_source_class="Producto",
        candidate_target_class="Pedido",
        candidate_source_cardinality="0..*",
        candidate_target_cardinality="1",
        candidate_name="contiene",
        is_equivalent=True,
    ),
    # Reversed with NON-swapped cardinalities -> NOT equivalent
    AssociationEquivalenceCase(
        source_class="Pedido",
        target_class="Producto",
        source_cardinality="1",
        target_cardinality="0..*",
        name="contiene",
        candidate_source_class="Producto",
        candidate_target_class="Pedido",
        candidate_source_cardinality="1",
        candidate_target_cardinality="0..*",
        candidate_name="contiene",
        is_equivalent=False,
    ),
    # Different name -> NOT equivalent
    AssociationEquivalenceCase(
        source_class="Pedido",
        target_class="Producto",
        source_cardinality="1",
        target_cardinality="0..*",
        name="contiene",
        candidate_source_class="Pedido",
        candidate_target_class="Producto",
        candidate_source_cardinality="1",
        candidate_target_cardinality="0..*",
        candidate_name="referencia",
        is_equivalent=False,
    ),
)
