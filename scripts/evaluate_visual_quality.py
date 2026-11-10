"""Evalúa la extracción UML real de Qwen contra un corpus de imágenes etiquetado.

Cada imagen se carga temporalmente en Cloudinary y se elimina después de inferir.
El proceso requiere credenciales configuradas y puede generar cargos del proveedor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.core.config import settings
from app.modules.assistant.application.ports.providers.ai_provider import ModelRole
from app.modules.assistant.application.services.visual.visual_contracts import VisualIntent
from app.modules.assistant.application.services.visual.visual_diagram_normalizer import (
    normalize_visual_diagram,
)
from app.modules.assistant.application.services.visual.visual_evidence import (
    VisualEvidenceExtractor,
)
from app.modules.assistant.infrastructure.external.cloudinary_image_provider import (
    CloudinaryImageProvider,
)
from app.modules.assistant.infrastructure.external.qwen_ai_provider import QwenAiProvider

CORPUS_DIR = (
    SERVER_ROOT
    / "tests/modules/assistant/fixtures/visual_quality_corpus"
)
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
MAX_CASES = 50
MAX_IMAGE_BYTES = 10 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_DATA_TYPES = {
    "UUID",
    "TEXT",
    "INTEGER",
    "DECIMAL",
    "BOOLEAN",
    "DATE",
    "TIMESTAMP",
}
SUPPORTED_RELATION_TYPES = {
    "ASSOCIATION",
    "AGGREGATION",
    "COMPOSITION",
    "GENERALIZATION",
    "REALIZATION",
    "DEPENDENCY",
}
SUPPORTED_CARDINALITIES = {"0..1", "1", "0..*", "1..*"}
FULL_DIAGRAM_INTENT = VisualIntent(
    mode="analyze",
    needs_image=True,
    visual_request=(
        "Reconoce todas las clases, atributos ordinarios y relaciones visibles. "
        "Devuelve los tipos de datos, tipos de relación y cardinalidades legibles."
    ),
    scope={"classes": "all", "attributes": "all", "relations": "all"},
)


def _load_manifest(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    resolved_path = path.resolve()
    try:
        manifest = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"No se pudo leer el manifiesto: {resolved_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("El manifiesto debe ser un objeto JSON con version=1.")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
        raise ValueError(f"El corpus debe contener entre 1 y {MAX_CASES} casos.")
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Cada caso del manifiesto debe ser un objeto.")
        case_id = case.get("id")
        image_name = case.get("image")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or case_id in case_ids
            or not isinstance(image_name, str)
            or not image_name.strip()
            or Path(image_name).is_absolute()
            or ".." in Path(image_name).parts
        ):
            raise ValueError("Cada caso requiere un ID único y una ruta de imagen relativa segura.")
        if (
            not isinstance(case.get("classes"), list)
            or not case["classes"]
            or not all(isinstance(name, str) and name.strip() for name in case["classes"])
            or not isinstance(case.get("attributes"), dict)
            or not case["attributes"]
            or not all(
                isinstance(name, str)
                and "." in name
                and isinstance(data_type, str)
                and data_type.strip().upper() in SUPPORTED_DATA_TYPES
                for name, data_type in case["attributes"].items()
            )
            or not isinstance(case.get("relations"), list)
            or not case["relations"]
            or case.get("diagram_kind") not in {"UML_CLASS", "ERD"}
        ):
            raise ValueError(f"El caso {case_id!r} no contiene etiquetas completas.")
        class_names = {_normalized_name(name) for name in case["classes"]}
        for attribute_name in case["attributes"]:
            class_name = attribute_name.split(".", 1)[0]
            if _normalized_name(class_name) not in class_names:
                raise ValueError(
                    f"El atributo {attribute_name!r} refiere a una clase no etiquetada."
                )
        for relation in case["relations"]:
            if (
                not isinstance(relation, dict)
                or _normalized_name(relation.get("source", "")) not in class_names
                or _normalized_name(relation.get("target", "")) not in class_names
                or relation.get("relation_type") not in SUPPORTED_RELATION_TYPES
                or relation.get("source_cardinality") not in SUPPORTED_CARDINALITIES
                or relation.get("target_cardinality") not in SUPPORTED_CARDINALITIES
            ):
                raise ValueError(f"El caso {case_id!r} tiene etiquetas de relación inválidas.")
        case_ids.add(case_id)
    return resolved_path.parent, cases


def _check_credentials() -> None:
    configured_values = {
        "QWEN_API_KEY": settings.QWEN_API_KEY.get_secret_value(),
        "CLOUDINARY_CLOUD_NAME": settings.CLOUDINARY_CLOUD_NAME,
        "CLOUDINARY_API_KEY": settings.CLOUDINARY_API_KEY,
        "CLOUDINARY_API_SECRET": settings.CLOUDINARY_API_SECRET,
    }
    missing = [name for name, value in configured_values.items() if not value.strip()]
    if missing:
        raise RuntimeError(
            "Configura estas variables en el entorno local antes de ejecutar la evaluación: "
            + ", ".join(missing)
        )


def _read_png(corpus_dir: Path, image_name: str) -> bytes:
    image_path = (corpus_dir / image_name).resolve()
    if corpus_dir.resolve() not in image_path.parents:
        raise ValueError(f"La imagen {image_name!r} sale del directorio del corpus.")
    image_data = image_path.read_bytes()
    if len(image_data) > MAX_IMAGE_BYTES or not image_data.startswith(PNG_SIGNATURE):
        raise ValueError(f"La imagen {image_name!r} no es un PNG válido o supera 10 MiB.")
    return image_data


async def _extract_case(
    *,
    case: dict[str, Any],
    corpus_dir: Path,
    extractor: VisualEvidenceExtractor,
    storage: CloudinaryImageProvider,
) -> dict[str, Any]:
    case_id = case["id"]
    image_data = _read_png(corpus_dir, case["image"])
    stored_image = None
    normalized = None
    extraction_error: Exception | None = None
    try:
        stored_image = await storage.upload(
            image_data,
            public_id=f"assistant/quality-evaluation/{uuid4().hex}",
        )
        evidence = await extractor.extract(stored_image.url, FULL_DIAGRAM_INTENT)
        normalized = normalize_visual_diagram(FULL_DIAGRAM_INTENT, evidence)
    except Exception as exc:
        extraction_error = exc
    finally:
        if stored_image is not None:
            try:
                await storage.delete(stored_image.public_id)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"Falló la eliminación temporal en Cloudinary para {case_id} "
                    f"({type(cleanup_error).__name__})."
                ) from (extraction_error or cleanup_error)
    if extraction_error is not None:
        raise RuntimeError(
            f"Falló la inferencia para {case_id} ({type(extraction_error).__name__})."
        ) from extraction_error
    if normalized is None:
        raise RuntimeError(f"La inferencia de {case_id} no produjo evidencia normalizada.")
    return normalized


def _normalized_name(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _relation_key(relation: dict[str, Any]) -> str:
    source = _normalized_name(relation.get("source", ""))
    target = _normalized_name(relation.get("target", ""))
    relation_type = _normalized_name(relation.get("relation_type", ""))
    source_cardinality = _normalized_name(relation.get("source_cardinality", ""))
    target_cardinality = _normalized_name(relation.get("target_cardinality", ""))
    if relation_type == "association" and target < source:
        source, target = target, source
        source_cardinality, target_cardinality = target_cardinality, source_cardinality
    return "|".join(
        (source, target, relation_type, source_cardinality, target_cardinality)
    )


def _expected_values(case: dict[str, Any]) -> dict[str, Counter[str]]:
    case_id = case["id"]
    return {
        "classes": Counter(
            f"{case_id}::{_normalized_name(name)}" for name in case["classes"]
        ),
        "attributes": Counter(
            f"{case_id}::{_normalized_name(name)}|{_normalized_name(data_type)}"
            for name, data_type in case["attributes"].items()
        ),
        "relations": Counter(
            f"{case_id}::{_relation_key(relation)}"
            for relation in case["relations"]
        ),
    }


def _actual_values(
    case_id: str, normalized: dict[str, Any]
) -> dict[str, Counter[str]]:
    classes = normalized.get("classes", [])
    return {
        "classes": Counter(
            f"{case_id}::{_normalized_name(item.get('name', ''))}"
            for item in classes
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ),
        "attributes": Counter(
            f"{case_id}::{_normalized_name(class_item.get('name', ''))}."
            f"{_normalized_name(attribute.get('name', ''))}|"
            f"{_normalized_name(attribute.get('data_type') or 'null')}"
            for class_item in classes
            if isinstance(class_item, dict)
            for attribute in class_item.get("attributes", [])
            if isinstance(attribute, dict)
        ),
        "relations": Counter(
            f"{case_id}::{_relation_key(relation)}"
            for relation in normalized.get("relations", [])
            if isinstance(relation, dict)
        ),
    }


def _score(expected: Counter[str], actual: Counter[str]) -> dict[str, Any]:
    true_positive = sum((expected & actual).values())
    false_positive = sum((actual - expected).values())
    false_negative = sum((expected - actual).values())
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def _meets_threshold(score: dict[str, Any], threshold: float) -> bool:
    true_positive = score["true_positive"]
    precision_denominator = true_positive + score["false_positive"]
    recall_denominator = true_positive + score["false_negative"]
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    return precision >= threshold and recall >= threshold


async def _run(dataset_path: Path, output_path: Path | None) -> int:
    _check_credentials()
    corpus_dir, cases = _load_manifest(dataset_path)
    provider = QwenAiProvider(settings=settings)
    extractor = VisualEvidenceExtractor(provider)
    storage = CloudinaryImageProvider()
    expected: dict[str, Counter[str]] = {
        category: Counter() for category in ("classes", "attributes", "relations")
    }
    actual: dict[str, Counter[str]] = {
        category: Counter() for category in ("classes", "attributes", "relations")
    }
    case_reports = []

    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] Evaluando {case['id']}...", flush=True)
        normalized = await _extract_case(
            case=case,
            corpus_dir=corpus_dir,
            extractor=extractor,
            storage=storage,
        )
        expected_case = _expected_values(case)
        actual_case = _actual_values(case["id"], normalized)
        for category in expected:
            expected[category].update(expected_case[category])
            actual[category].update(actual_case[category])
        case_reports.append(
            {
                "id": case["id"],
                "supported": normalized.get("supported"),
                "diagram_kind": normalized.get("diagram_kind"),
                "uncertainties": normalized.get("uncertainties", []),
                "metrics": {
                    category: _score(expected_case[category], actual_case[category])
                    for category in expected
                },
            }
        )
        print(f"[{index}/{len(cases)}] Terminado {case['id']}.", flush=True)

    metrics = {
        category: _score(expected[category], actual[category])
        for category in expected
    }
    passed = all(_meets_threshold(metrics[category], 0.9) for category in metrics)
    report = {
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_role": ModelRole.VISION.value,
        "model": settings.QWEN_MODEL_VISION,
        "dataset": str(dataset_path.resolve()),
        "cases": case_reports,
        "metrics": metrics,
        "threshold": 0.9,
        "passed": passed,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path is not None:
        output_path.resolve().write_text(rendered + "\n", encoding="utf-8")
        print(f"Informe guardado en {output_path.resolve()}.", flush=True)
    print(rendered)
    return 0 if passed else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=MANIFEST_PATH,
        help="Manifiesto JSON del corpus visual etiquetado.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ruta opcional para guardar el informe JSON de la evaluación.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    try:
        raise SystemExit(asyncio.run(_run(arguments.dataset, arguments.output)))
    except (RuntimeError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
