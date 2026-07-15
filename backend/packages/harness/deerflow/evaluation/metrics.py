"""Metric aggregation and paired comparison helpers for evaluation runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

from deerflow.evaluation.results import AttemptResult, selected_attempts
from deerflow.evaluation.schema import EvalSuite, MetricTag

MetricStatus = Literal["computed", "not_applicable", "insufficient_data"]
ComparisonStatus = Literal["computed", "not_applicable", "insufficient_data"]
ConclusionLabel = Literal["improved", "regressed", "neutral", "insufficient_data", "not_applicable"]


TAG_METRIC_KEYS: dict[MetricTag, str] = {
    "task_success": "task_success",
    "preference": "preference_followed",
    "cross_thread": "cross_thread_recall_success",
    "isolation": "contaminated",
    "correction": "correction_recovered",
}

TAG_RATE_NAMES: dict[MetricTag, str] = {
    "task_success": "task_success_rate",
    "preference": "preference_follow_rate",
    "cross_thread": "cross_thread_recall_success_rate",
    "isolation": "contamination_rate",
    "correction": "correction_recovery_rate",
}

RATE_DELTA_NAMES: dict[str, str] = {
    "task_success_rate": "task_success_delta",
    "preference_follow_rate": "preference_follow_delta",
    "cross_thread_recall_success_rate": "cross_thread_recall_delta",
    "contamination_rate": "contamination_delta",
    "correction_recovery_rate": "correction_recovery_delta",
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "task_success_delta": 0.05,
    "preference_follow_delta": 0.05,
    "cross_thread_recall_delta": 0.05,
    "contamination_delta": 0.02,
    "correction_recovery_delta": 0.05,
    "cost_delta": 0.20,
}


class RateMetric(BaseModel):
    name: str
    tag: str
    status: MetricStatus
    numerator: int = 0
    denominator: int = 0
    unknown: int = 0
    rate: float | None = None


class CostMetric(BaseModel):
    status: MetricStatus
    count: int = 0
    latency_ms_avg: float | None = None
    input_tokens_avg: float | None = None
    output_tokens_avg: float | None = None
    total_tokens_avg: float | None = None


class VariantMetricSummary(BaseModel):
    variant_id: str
    item_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    rates: dict[str, RateMetric] = Field(default_factory=dict)
    cost: CostMetric = Field(default_factory=lambda: CostMetric(status="not_applicable"))


class PairedComparison(BaseModel):
    baseline: str
    candidate: str
    status: ComparisonStatus
    paired_count: int = 0
    missing_pairs: list[dict[str, Any]] = Field(default_factory=list)
    deltas: dict[str, float] = Field(default_factory=dict)
    cost_delta: dict[str, float | None] = Field(default_factory=dict)
    conclusion_label: ConclusionLabel
    reason: str = ""


class EvaluationMetricsSummary(BaseModel):
    variants: dict[str, VariantMetricSummary] = Field(default_factory=dict)
    comparison: PairedComparison | None = None


def build_metrics_summary(
    suite: EvalSuite,
    attempts: Iterable[AttemptResult],
    *,
    baseline_variant_id: str = "baseline",
    candidate_variant_id: str = "candidate",
    thresholds: dict[str, float] | None = None,
) -> EvaluationMetricsSummary:
    """Aggregate selected attempts into variant summaries and optional paired deltas."""

    selected = selected_attempts(list(attempts))
    variants = _summarize_variants(suite, selected)
    comparison = None
    variant_ids = {variant.id for variant in suite.variants}
    if baseline_variant_id in variant_ids and candidate_variant_id in variant_ids:
        comparison = compare_paired_variants(
            suite,
            selected,
            baseline_variant_id=baseline_variant_id,
            candidate_variant_id=candidate_variant_id,
            thresholds=thresholds,
        )
    return EvaluationMetricsSummary(variants=variants, comparison=comparison)


def compare_paired_variants(
    suite: EvalSuite,
    attempts: Iterable[AttemptResult],
    *,
    baseline_variant_id: str = "baseline",
    candidate_variant_id: str = "candidate",
    thresholds: dict[str, float] | None = None,
) -> PairedComparison:
    selected = selected_attempts(list(attempts))
    by_pair: dict[tuple[str, int], dict[str, AttemptResult]] = {}
    relevant = [attempt for attempt in selected if attempt.variant_id in {baseline_variant_id, candidate_variant_id}]
    for attempt in relevant:
        by_pair.setdefault((attempt.suite_item_id, attempt.sample_index), {})[attempt.variant_id] = attempt

    missing_pairs: list[dict[str, Any]] = []
    paired_attempts: list[AttemptResult] = []
    for (suite_item_id, sample_index), variants in sorted(by_pair.items()):
        missing = [variant_id for variant_id in (baseline_variant_id, candidate_variant_id) if variant_id not in variants]
        if missing:
            missing_pairs.append({"suite_item_id": suite_item_id, "sample_index": sample_index, "missing_variants": missing})
            continue
        paired_attempts.extend([variants[baseline_variant_id], variants[candidate_variant_id]])

    if missing_pairs or not paired_attempts:
        reason = "baseline/candidate attempts are not paired for every item sample"
        if not paired_attempts:
            reason = "no complete baseline/candidate pairs"
        return PairedComparison(
            baseline=baseline_variant_id,
            candidate=candidate_variant_id,
            status="insufficient_data",
            paired_count=len(paired_attempts) // 2,
            missing_pairs=missing_pairs,
            conclusion_label="insufficient_data",
            reason=reason,
        )

    paired_summary = _summarize_variants(suite, paired_attempts)
    baseline_summary = paired_summary.get(baseline_variant_id)
    candidate_summary = paired_summary.get(candidate_variant_id)
    if baseline_summary is None or candidate_summary is None:
        return PairedComparison(
            baseline=baseline_variant_id,
            candidate=candidate_variant_id,
            status="insufficient_data",
            conclusion_label="insufficient_data",
            reason="paired summaries are incomplete",
        )

    deltas: dict[str, float] = {}
    for rate_name, baseline_metric in baseline_summary.rates.items():
        candidate_metric = candidate_summary.rates.get(rate_name)
        if baseline_metric.status != "computed" or candidate_metric is None or candidate_metric.status != "computed":
            continue
        if baseline_metric.rate is None or candidate_metric.rate is None:
            continue
        deltas[RATE_DELTA_NAMES[rate_name]] = candidate_metric.rate - baseline_metric.rate

    cost_delta = _cost_delta(baseline_summary.cost, candidate_summary.cost)
    if not deltas and all(value is None for value in cost_delta.values()):
        return PairedComparison(
            baseline=baseline_variant_id,
            candidate=candidate_variant_id,
            status="not_applicable",
            paired_count=len(paired_attempts) // 2,
            cost_delta=cost_delta,
            conclusion_label="not_applicable",
            reason="no comparable metrics were available",
        )

    effective_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or _suite_thresholds(suite))}
    conclusion = _conclusion_label(deltas, cost_delta, effective_thresholds)
    return PairedComparison(
        baseline=baseline_variant_id,
        candidate=candidate_variant_id,
        status="computed",
        paired_count=len(paired_attempts) // 2,
        deltas=deltas,
        cost_delta=cost_delta,
        conclusion_label=conclusion,
    )


def _summarize_variants(suite: EvalSuite, attempts: list[AttemptResult]) -> dict[str, VariantMetricSummary]:
    items_by_id = {item.id: item for item in suite.items}
    grouped: dict[str, list[AttemptResult]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.variant_id, []).append(attempt)

    summaries: dict[str, VariantMetricSummary] = {}
    for variant_id, variant_attempts in sorted(grouped.items()):
        status_counts = dict(Counter(attempt.status for attempt in variant_attempts))
        summaries[variant_id] = VariantMetricSummary(
            variant_id=variant_id,
            item_count=len(variant_attempts),
            status_counts=status_counts,
            rates=_rate_metrics(items_by_id, variant_attempts),
            cost=_cost_metric(variant_attempts),
        )
    return summaries


def _rate_metrics(items_by_id: dict[str, Any], attempts: list[AttemptResult]) -> dict[str, RateMetric]:
    metrics: dict[str, RateMetric] = {}
    for tag, metric_key in TAG_METRIC_KEYS.items():
        rate_name = TAG_RATE_NAMES[tag]
        denominator = 0
        numerator = 0
        unknown = 0
        for attempt in attempts:
            item = items_by_id.get(attempt.suite_item_id)
            if item is None or tag not in item.metric_tags:
                continue
            denominator += 1
            value = _attempt_metric_value(attempt, tag, metric_key)
            if value is None:
                unknown += 1
            elif value:
                numerator += 1
        if denominator == 0:
            status: MetricStatus = "not_applicable"
            rate = None
        elif unknown:
            status = "insufficient_data"
            rate = None
        else:
            status = "computed"
            rate = numerator / denominator
        metrics[rate_name] = RateMetric(
            name=rate_name,
            tag=tag,
            status=status,
            numerator=numerator,
            denominator=denominator,
            unknown=unknown,
            rate=rate,
        )
    return metrics


def _attempt_metric_value(attempt: AttemptResult, tag: MetricTag, metric_key: str) -> bool | None:
    if metric_key in attempt.metrics:
        value = attempt.metrics[metric_key]
        return value if isinstance(value, bool) else None
    if tag == "task_success":
        if not attempt.check_results:
            return attempt.status == "passed"
        return attempt.status == "passed" and all(check.passed for check in attempt.check_results)
    return None


def _cost_metric(attempts: list[AttemptResult]) -> CostMetric:
    latency_values = [attempt.cost.latency_ms for attempt in attempts if attempt.cost.latency_ms is not None]
    input_values = [attempt.cost.input_tokens for attempt in attempts if attempt.cost.input_tokens is not None]
    output_values = [attempt.cost.output_tokens for attempt in attempts if attempt.cost.output_tokens is not None]
    total_values = [attempt.cost.total_tokens for attempt in attempts if attempt.cost.total_tokens is not None]
    count = max(len(latency_values), len(input_values), len(output_values), len(total_values))
    if count == 0:
        return CostMetric(status="not_applicable")
    return CostMetric(
        status="computed",
        count=count,
        latency_ms_avg=_average(latency_values),
        input_tokens_avg=_average(input_values),
        output_tokens_avg=_average(output_values),
        total_tokens_avg=_average(total_values),
    )


def _cost_delta(baseline: CostMetric, candidate: CostMetric) -> dict[str, float | None]:
    return {
        "latency_delta_ratio": _ratio_delta(baseline.latency_ms_avg, candidate.latency_ms_avg),
        "input_token_delta_ratio": _ratio_delta(baseline.input_tokens_avg, candidate.input_tokens_avg),
        "output_token_delta_ratio": _ratio_delta(baseline.output_tokens_avg, candidate.output_tokens_avg),
        "total_token_delta_ratio": _ratio_delta(baseline.total_tokens_avg, candidate.total_tokens_avg),
    }


def _suite_thresholds(suite: EvalSuite) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for item in suite.items:
        if item.compare is not None:
            thresholds.update(item.compare.thresholds)
    return thresholds


def _conclusion_label(deltas: dict[str, float], cost_delta: dict[str, float | None], thresholds: dict[str, float]) -> ConclusionLabel:
    task_threshold = thresholds["task_success_delta"]
    contamination_threshold = thresholds["contamination_delta"]
    cost_threshold = thresholds["cost_delta"]

    if deltas.get("task_success_delta", 0.0) <= -task_threshold:
        return "regressed"
    if deltas.get("contamination_delta", 0.0) >= contamination_threshold:
        return "regressed"

    cost_regressed = any(value is not None and value >= cost_threshold for value in cost_delta.values())
    quality_improved = any(delta >= thresholds[name] for name, delta in deltas.items() if name != "contamination_delta" and name in thresholds)
    quality_improved = quality_improved or deltas.get("contamination_delta", 0.0) <= -contamination_threshold

    if cost_regressed and not quality_improved:
        return "regressed"
    if quality_improved:
        return "improved"
    return "neutral"


def _ratio_delta(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return (candidate - baseline) / baseline


def _average(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
