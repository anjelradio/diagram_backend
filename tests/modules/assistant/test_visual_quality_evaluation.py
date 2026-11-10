"""Evaluación reproducible del contrato; no mide la calidad del modelo remoto."""

import json

from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualIntent,
    parse_visual_evidence,
)
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)
from tests.modules.assistant.fixtures.visual_diagrams import (
    MOCK_VISUAL_EVIDENCE,
    VISUAL_DIAGRAM_CASES,
)


def _scores(expected: set[str], actual: set[str]) -> tuple[float, float]:
    if not expected and not actual:
        return 1.0, 1.0
    precision = len(expected & actual) / len(actual) if actual else 0.0
    recall = len(expected & actual) / len(expected) if expected else 0.0
    return precision, recall


def test_labeled_contract_fixtures_score_at_least_90_percent_per_category():
    precision_by_category = {"classes": [], "attributes": [], "relations": []}
    recall_by_category = {"classes": [], "attributes": [], "relations": []}
    intent = VisualIntent(
        mode="mutate",
        needs_image=True,
        visual_request="Importa el contenido visible",
        scope={"classes": "all", "attributes": "all", "relations": "all"},
    )

    for case in VISUAL_DIAGRAM_CASES:
        parsed = parse_visual_evidence(json.dumps(MOCK_VISUAL_EVIDENCE[case["id"]]))
        normalized = normalize_visual_diagram(intent, parsed)
        assert normalized["supported"] == case["supported"]
        if case["uncertainties"]:
            assert normalized["uncertainties"]
        expected_classes = set(case["classes"])
        actual_classes = {item["name"] for item in normalized["classes"]}
        expected_attributes = {
            f"{class_name}.{name}"
            for class_name, names in case.get("attributes_by_class", {}).items()
            for name in names
        }
        actual_attributes = {
            f"{class_item['name']}.{attribute['name']}"
            for class_item in normalized["classes"]
            for attribute in class_item["attributes"]
        }
        expected_relations = {
            f"{item['source']}-{item['target']}"
            for item in case["relations"]
            if item.get("cardinality") is not None
        }
        actual_relations = {
            f"{item['source']}-{item['target']}" for item in normalized["relations"]
        }
        for category, expected, actual in (
            ("classes", expected_classes, actual_classes),
            ("attributes", expected_attributes, actual_attributes),
            ("relations", expected_relations, actual_relations),
        ):
            # Relaciones ilegibles deben bloquearse, no puntuarse como hechos.
            if category == "relations" and case["uncertainties"]:
                continue
            precision, recall = _scores(expected, actual)
            precision_by_category[category].append(precision)
            recall_by_category[category].append(recall)

    for category in precision_by_category:
        assert sum(precision_by_category[category]) / len(precision_by_category[category]) >= 0.9
        assert sum(recall_by_category[category]) / len(recall_by_category[category]) >= 0.9


def test_evaluation_dataset_includes_visual_key_rules_as_derived_effects():
    # PK/FK/bridge labels are intentionally not ordinary attributes in the fixture.
    assert all("id" not in names for case in VISUAL_DIAGRAM_CASES for names in case.get("attributes_by_class", {}).values())
