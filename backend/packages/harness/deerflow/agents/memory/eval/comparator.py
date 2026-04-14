from __future__ import annotations

import logging
from dataclasses import dataclass

from deerflow.agents.memory.eval.types import ComparisonResult, ReplayResult

logger = logging.getLogger(__name__)


def _budget_utilization(result: ReplayResult) -> float:
    max_tokens = result.tokens_used + result.tokens_remaining
    if max_tokens == 0:
        return 0.0
    return sum(rf.token_cost for rf in result.ranked_facts if rf.included) / max_tokens


def _drop_rate(result: ReplayResult) -> float:
    total = result.selected_count + result.dropped_count
    if total == 0:
        return 0.0
    return result.dropped_count / total


def _correction_hit_rate(result: ReplayResult) -> float:
    corrections = [rf for rf in result.ranked_facts if rf.category == "correction"]
    if not corrections:
        return 0.0
    return sum(1 for rf in corrections if rf.included) / len(corrections)


def _selection_overlap(baseline: ReplayResult, comparison: ReplayResult) -> float:
    a = {rf.fact_id for rf in baseline.ranked_facts if rf.included}
    b = {rf.fact_id for rf in comparison.ranked_facts if rf.included}
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _rank_correlation(baseline: ReplayResult, comparison: ReplayResult) -> float:
    """Simplified Spearman: pairwise order agreements / total pairs."""
    base_order = {rf.fact_id: rf.new_rank for rf in baseline.ranked_facts}
    comp_order = {rf.fact_id: rf.new_rank for rf in comparison.ranked_facts}
    common = [fid for fid in base_order if fid in comp_order]
    if len(common) < 2:
        return 1.0
    agreements = 0
    total = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            fi, fj = common[i], common[j]
            base_agrees = (base_order[fi] < base_order[fj]) == (comp_order[fi] < comp_order[fj])
            agreements += int(base_agrees)
            total += 1
    if total == 0:
        return 1.0
    return agreements / total


def _compute_metrics(result: ReplayResult) -> dict[str, float]:
    return {
        "budget_utilization": _budget_utilization(result),
        "drop_rate": _drop_rate(result),
        "correction_hit_rate": _correction_hit_rate(result),
    }


def compute_summary(comparisons: list[ComparisonResult]) -> dict[str, float]:
    """Average deltas across all comparison results."""
    if not comparisons:
        return {}
    totals: dict[str, float] = {}
    for cr in comparisons:
        for k, v in cr.deltas.items():
            totals[k] = totals.get(k, 0.0) + v
    count = len(comparisons)
    return {k: v / count for k, v in sorted(totals.items())}


@dataclass(slots=True)
class MetricsComparator:
    baseline_name: str

    def compare(self, all_results: dict[str, list[ReplayResult]]) -> list[ComparisonResult]:
        if self.baseline_name not in all_results:
            logger.warning("Baseline strategy %r not found in results. Returning empty list.", self.baseline_name)
            return []

        baseline_by_trace = {r.trace_id: r for r in all_results[self.baseline_name]}
        output: list[ComparisonResult] = []

        for strategy_name, results in all_results.items():
            if strategy_name == self.baseline_name:
                continue
            for comp_result in results:
                trace_id = comp_result.trace_id
                if trace_id not in baseline_by_trace:
                    logger.debug("Trace %r not found in baseline; skipping.", trace_id)
                    continue
                base_result = baseline_by_trace[trace_id]
                base_metrics = _compute_metrics(base_result)
                comp_metrics = _compute_metrics(comp_result)
                overlap = _selection_overlap(base_result, comp_result)
                corr = _rank_correlation(base_result, comp_result)
                base_metrics["selection_overlap"] = overlap
                base_metrics["rank_correlation"] = corr
                comp_metrics["selection_overlap"] = overlap
                comp_metrics["rank_correlation"] = corr
                deltas = {k: comp_metrics[k] - base_metrics[k] for k in base_metrics}
                output.append(
                    ComparisonResult(
                        trace_id=trace_id,
                        baseline_strategy=self.baseline_name,
                        comparison_strategy=strategy_name,
                        baseline_metrics=base_metrics,
                        comparison_metrics=comp_metrics,
                        deltas=deltas,
                    )
                )
        return output

    def summarize(self, comparisons: list[ComparisonResult]) -> dict[str, float]:
        return compute_summary(comparisons)
