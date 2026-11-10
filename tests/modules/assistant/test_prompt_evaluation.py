"""Pruebas unitarias para métricas de telemetría de prompts y evaluación semántica."""

from uuid import uuid4
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.prompting.prompt_metrics import (
    PromptInferenceMetric,
    PromptMetricsCollector,
    PromptTokenBreakdown,
    QualityEvaluationReport,
)


def test_metrics_record_preserves_privacy_without_raw_text():
    breakdown = PromptTokenBreakdown(
        instruction_tokens=450,
        tool_tokens=200,
        memory_tokens=50,
        evidence_tokens=0,
    )
    metric = PromptInferenceMetric(
        inference_id="inf-1234",
        message_id="msg-5678",
        purpose="task_execution",
        phase="execution",
        variant="modular",
        version="modular-1.0.0",
        modules=("core_universal", "phase_execution", "module_attributes"),
        token_breakdown=breakdown,
        input_tokens=710,
        output_tokens=45,
        cached_tokens=128,
        duration_ms=452.3,
    )

    safe_dict = metric.to_safe_dict()

    # Verificar que solo contiene metadata, números y nombres de módulos
    assert safe_dict["inference_id"] == "inf-1234"
    assert safe_dict["variant"] == "modular"
    assert safe_dict["modules"] == ["core_universal", "phase_execution", "module_attributes"]
    assert safe_dict["estimated_breakdown"]["instruction_tokens"] == 450
    assert safe_dict["estimated_breakdown"]["total_estimated"] == 700
    assert safe_dict["actual_usage"]["cached_tokens"] == 128
    assert safe_dict["actual_usage"]["duration_ms"] == 452.3

    # Invariante de privacidad: ningún texto del usuario ni del asistente presente
    for key, value in safe_dict.items():
        assert "prompt" not in key.lower() or key in ("estimated_breakdown",)
        assert not isinstance(value, str) or ("crear" not in value and "SELECT" not in value)


def test_metrics_handles_missing_usage_and_cache_gracefully():
    breakdown = PromptTokenBreakdown(instruction_tokens=900)
    metric = PromptInferenceMetric(
        inference_id="inf-9999",
        purpose="planning",
        phase="planning",
        variant="legacy",
        version="legacy-1.0.0",
        modules=("legacy_planner_prompt",),
        token_breakdown=breakdown,
        input_tokens=None,
        output_tokens=None,
        cached_tokens=None,
        duration_ms=None,
    )

    safe_dict = metric.to_safe_dict()
    assert safe_dict["actual_usage"]["input_tokens"] is None
    assert safe_dict["actual_usage"]["cached_tokens"] is None
    assert safe_dict["actual_usage"]["duration_ms"] is None


def test_metrics_collector_aggregates_different_variants():
    collector = PromptMetricsCollector()
    b_leg = PromptTokenBreakdown(instruction_tokens=1000)
    b_mod = PromptTokenBreakdown(instruction_tokens=500)

    collector.record(
        PromptInferenceMetric(
            inference_id="1",
            purpose="task",
            phase="execution",
            variant="legacy",
            version="1.0",
            modules=("legacy_tool_prompt",),
            token_breakdown=b_leg,
            input_tokens=1050,
        )
    )
    collector.record(
        PromptInferenceMetric(
            inference_id="2",
            purpose="task",
            phase="execution",
            variant="modular",
            version="1.0",
            modules=("core_universal", "phase_execution"),
            token_breakdown=b_mod,
            input_tokens=550,
            cached_tokens=200,
        )
    )

    summary = collector.get_summary_by_variant()
    assert "legacy" in summary
    assert "modular" in summary
    assert summary["legacy"]["avg_instruction_tokens"] == 1000.0
    assert summary["modular"]["avg_instruction_tokens"] == 500.0
    assert summary["modular"]["total_cached_tokens"] == 200


def test_quality_evaluation_report_promotion_thresholds():
    # Reporte ideal que cumple todos los criterios
    ideal_report = QualityEvaluationReport(
        total_scenarios=42,
        security_passed=10,
        security_total=10,
        specialized_passed=16,
        specialized_total=16,
        equivalent_scenarios=41,
        simple_instruction_reduction_pct=48.5,
        regressions=[],
    )
    assert ideal_report.security_rate == 1.0
    assert ideal_report.specialized_rate == 1.0
    assert ideal_report.equivalence_rate >= 0.95
    assert ideal_report.is_promotable is True

    # Falla criterio de seguridad (SC-001)
    sec_fail = QualityEvaluationReport(
        total_scenarios=42,
        security_passed=9,
        security_total=10,
        specialized_passed=16,
        specialized_total=16,
        equivalent_scenarios=41,
        simple_instruction_reduction_pct=50.0,
        regressions=[],
    )
    assert sec_fail.is_promotable is False

    # Falla criterio de equivalencia global (SC-002: <95%)
    eq_fail = QualityEvaluationReport(
        total_scenarios=42,
        security_passed=10,
        security_total=10,
        specialized_passed=16,
        specialized_total=16,
        equivalent_scenarios=38,  # 38/42 = 90.4% < 95%
        simple_instruction_reduction_pct=50.0,
        regressions=[],
    )
    assert eq_fail.is_promotable is False

    # Falla reducción de instrucciones (SC-003: <30%)
    red_fail = QualityEvaluationReport(
        total_scenarios=42,
        security_passed=10,
        security_total=10,
        specialized_passed=16,
        specialized_total=16,
        equivalent_scenarios=42,
        simple_instruction_reduction_pct=25.0,  # < 30%
        regressions=[],
    )
    assert red_fail.is_promotable is False

    # Regresión reproducible pendiente (SC-005)
    reg_fail = QualityEvaluationReport(
        total_scenarios=42,
        security_passed=10,
        security_total=10,
        specialized_passed=16,
        specialized_total=16,
        equivalent_scenarios=42,
        simple_instruction_reduction_pct=45.0,
        regressions=[{"scenario_id": "SCN-04", "issue": "Missing attribute"}],
    )
    assert reg_fail.is_promotable is False


def test_ai_result_supports_cached_tokens_and_duration_ms():
    res = AiResult(
        text="OK",
        model_role=ModelRole.MAIN,
        model="qwen3.7-plus",
        input_tokens=100,
        output_tokens=25,
        cached_tokens=64,
        duration_ms=312.4,
    )
    assert res.cached_tokens == 64
    assert res.duration_ms == 312.4
