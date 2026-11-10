"""Registro de telemetría y métricas de composición de prompts sin almacenar textos privados.

Cumple con FR-008, SC-001 a SC-005, T022 y T023:
- Registra descomposición estimada: instrucciones, herramientas, memoria, evidencia.
- Registra telemetría real opcional: input_tokens, output_tokens, cached_tokens, duration_ms.
- Enlaza message_id, inference_id, variant, version, modules y purpose.
- Invariante de privacidad estricto: NUNCA almacena textos privados, prompts de usuario ni esquemas internos.
- Evalúa criterios de promoción (100% seguridad/especializados, >=95% equivalencia, >=30% reducción de instrucciones).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PromptTokenBreakdown:
    """Estimaciones separadas de volumen de tokens por categoría."""

    instruction_tokens: int
    tool_tokens: int = 0
    memory_tokens: int = 0
    evidence_tokens: int = 0

    @property
    def total_estimated_tokens(self) -> int:
        return (
            self.instruction_tokens
            + self.tool_tokens
            + self.memory_tokens
            + self.evidence_tokens
        )


@dataclass(frozen=True, slots=True)
class PromptInferenceMetric:
    """Registro inmutable de una inferencia para auditoría y evaluación de calidad."""

    inference_id: str
    purpose: str
    phase: str
    variant: str
    version: str
    modules: tuple[str, ...]
    token_breakdown: PromptTokenBreakdown
    message_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    duration_ms: float | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_safe_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario seguro garantizando que no existan textos privados."""
        return {
            "inference_id": self.inference_id,
            "message_id": self.message_id,
            "purpose": self.purpose,
            "phase": self.phase,
            "variant": self.variant,
            "version": self.version,
            "modules": list(self.modules),
            "estimated_breakdown": {
                "instruction_tokens": self.token_breakdown.instruction_tokens,
                "tool_tokens": self.token_breakdown.tool_tokens,
                "memory_tokens": self.token_breakdown.memory_tokens,
                "evidence_tokens": self.token_breakdown.evidence_tokens,
                "total_estimated": self.token_breakdown.total_estimated_tokens,
            },
            "actual_usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cached_tokens": self.cached_tokens,
                "duration_ms": self.duration_ms,
            },
            "timestamp": self.timestamp,
        }


class PromptMetricsCollector:
    """Colector en memoria para auditar y evaluar métricas durante ejecuciones o benchmarks."""

    def __init__(self) -> None:
        self._records: list[PromptInferenceMetric] = []

    def record(self, metric: PromptInferenceMetric) -> None:
        self._records.append(metric)

    @property
    def records(self) -> tuple[PromptInferenceMetric, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records.clear()

    def get_summary_by_variant(self) -> dict[str, dict[str, Any]]:
        """Calcula agregados por variante para comparar legacy vs modular."""
        by_variant: dict[str, list[PromptInferenceMetric]] = {}
        for r in self._records:
            by_variant.setdefault(r.variant, []).append(r)

        summary = {}
        for var, items in by_variant.items():
            total_est_instructions = sum(i.token_breakdown.instruction_tokens for i in items)
            total_input = sum(i.input_tokens for i in items if i.input_tokens is not None)
            total_cached = sum(i.cached_tokens for i in items if i.cached_tokens is not None)
            summary[var] = {
                "count": len(items),
                "total_estimated_instruction_tokens": total_est_instructions,
                "avg_instruction_tokens": total_est_instructions / len(items) if items else 0,
                "total_input_tokens": total_input,
                "total_cached_tokens": total_cached,
            }
        return summary


@dataclass(frozen=True, slots=True)
class QualityEvaluationReport:
    """Informe de evaluación de calidad semántica comparando variantes."""

    total_scenarios: int
    security_passed: int
    security_total: int
    specialized_passed: int
    specialized_total: int
    equivalent_scenarios: int
    simple_instruction_reduction_pct: float
    regressions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def security_rate(self) -> float:
        return (self.security_passed / self.security_total) if self.security_total > 0 else 1.0

    @property
    def specialized_rate(self) -> float:
        return (self.specialized_passed / self.specialized_total) if self.specialized_total > 0 else 1.0

    @property
    def equivalence_rate(self) -> float:
        return (self.equivalent_scenarios / self.total_scenarios) if self.total_scenarios > 0 else 1.0

    @property
    def is_promotable(self) -> bool:
        """Criterios de promoción (SC-001 a SC-005):
        - SC-001: 100% seguridad preservada
        - SC-002: >=95% equivalencia global
        - SC-003: >=30% reducción de instrucciones en simples
        - SC-004: 100% especializados preservados
        - SC-005: Sin regresiones reproducibles no resueltas
        """
        return (
            self.security_rate >= 1.0
            and self.specialized_rate >= 1.0
            and self.equivalence_rate >= 0.95
            and self.simple_instruction_reduction_pct >= 30.0
            and len(self.regressions) == 0
        )
