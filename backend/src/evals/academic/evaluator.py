"""Evaluator entrypoints for academic quality benchmarks."""

from __future__ import annotations

import math
import random
from itertools import product

from .metrics import (
    metric_abstract_body_consistency,
    metric_citation_fidelity,
    metric_claim_grounding,
    metric_cross_modality_synthesis,
    metric_long_horizon_consistency,
    metric_reviewer_rebuttal_completeness,
    metric_venue_fit,
)
from .schemas import AcademicEvalCase, AcademicEvalResult, AcademicEvalSummary

_METRIC_KEYS: tuple[str, ...] = (
    "citation_fidelity",
    "claim_grounding",
    "abstract_body_consistency",
    "reviewer_rebuttal_completeness",
    "venue_fit",
    "cross_modality_synthesis",
    "long_horizon_consistency",
)

_BASE_WEIGHTS: dict[str, float] = {
    "citation_fidelity": 1.0,
    "claim_grounding": 1.25,
    "abstract_body_consistency": 1.0,
    "reviewer_rebuttal_completeness": 0.85,
    "venue_fit": 1.0,
    "cross_modality_synthesis": 0.95,
    "long_horizon_consistency": 0.95,
}

_DOMAIN_MULTIPLIERS: dict[str, dict[str, float]] = {
    "ai_cs": {
        "venue_fit": 1.2,
        "cross_modality_synthesis": 1.2,
        "claim_grounding": 1.1,
    },
    "biomed": {
        "citation_fidelity": 1.2,
        "claim_grounding": 1.2,
        "reviewer_rebuttal_completeness": 1.15,
    },
}

_VENUE_MULTIPLIERS: dict[str, dict[str, float]] = {
    "neurips": {
        "venue_fit": 1.25,
        "cross_modality_synthesis": 1.2,
        "reviewer_rebuttal_completeness": 1.1,
    },
    "icml": {
        "venue_fit": 1.2,
        "cross_modality_synthesis": 1.2,
    },
    "nature": {
        "citation_fidelity": 1.2,
        "claim_grounding": 1.2,
        "long_horizon_consistency": 1.1,
    },
    "cell": {
        "citation_fidelity": 1.15,
        "claim_grounding": 1.15,
        "reviewer_rebuttal_completeness": 1.1,
    },
}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(raw.get(metric, 0.0))) for metric in _METRIC_KEYS)
    if total <= 0:
        uniform = 1.0 / float(len(_METRIC_KEYS))
        return {metric: uniform for metric in _METRIC_KEYS}
    return {metric: max(0.0, float(raw.get(metric, 0.0))) / total for metric in _METRIC_KEYS}


def _resolve_metric_weights(case: AcademicEvalCase) -> dict[str, float]:
    raw = dict(_BASE_WEIGHTS)
    domain_key = str(case.domain or "").strip().lower()
    venue_key = str(case.venue or "").strip().lower()
    for metric, multiplier in (_DOMAIN_MULTIPLIERS.get(domain_key) or {}).items():
        raw[metric] = raw.get(metric, 1.0) * float(multiplier)
    for metric, multiplier in (_VENUE_MULTIPLIERS.get(venue_key) or {}).items():
        raw[metric] = raw.get(metric, 1.0) * float(multiplier)
    return _normalize_weights(raw)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _score_to_accept_prob(score: float) -> float:
    # Prior calibration curve around realistic decision boundaries.
    return max(0.0001, min(0.9999, _sigmoid((float(score) - 0.58) * 6.0)))


def _roc_auc_pairwise(probs: list[float], labels: list[int]) -> float:
    pos = [p for p, y in zip(probs, labels, strict=False) if y == 1]
    neg = [p for p, y in zip(probs, labels, strict=False) if y == 0]
    if not pos or not neg:
        return 0.0
    pair_scores: list[float] = []
    for p_pos, p_neg in product(pos, neg):
        if p_pos > p_neg:
            pair_scores.append(1.0)
        elif p_pos == p_neg:
            pair_scores.append(0.5)
        else:
            pair_scores.append(0.0)
    return _mean(pair_scores)


def _expected_calibration_error(probs: list[float], labels: list[int], *, bins: int = 10) -> float:
    if not probs or not labels or len(probs) != len(labels):
        return 0.0
    n = len(probs)
    ece = 0.0
    for idx in range(bins):
        low = float(idx) / float(bins)
        high = float(idx + 1) / float(bins)
        bucket = [
            (p, y)
            for p, y in zip(probs, labels, strict=False)
            if (p >= low and (p < high or (idx == bins - 1 and p <= high)))
        ]
        if not bucket:
            continue
        bucket_acc = _mean([float(y) for _, y in bucket])
        bucket_conf = _mean([float(p) for p, _ in bucket])
        ece += (len(bucket) / n) * abs(bucket_acc - bucket_conf)
    return ece


def _bootstrap_mean_ci(values: list[float], *, samples: int = 400, seed: int = 42) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(_mean(sample))
    means.sort()
    low_idx = max(0, int(samples * 0.025) - 1)
    high_idx = min(samples - 1, int(samples * 0.975))
    return means[low_idx], means[high_idx]


def _bootstrap_auc_ci(probs: list[float], labels: list[int], *, samples: int = 300, seed: int = 43) -> tuple[float, float]:
    if len(probs) <= 2 or len(labels) != len(probs):
        auc = _roc_auc_pairwise(probs, labels)
        return auc, auc
    if len({int(x) for x in labels}) < 2:
        auc = _roc_auc_pairwise(probs, labels)
        return auc, auc
    rng = random.Random(seed)
    n = len(probs)
    aucs: list[float] = []
    for _ in range(samples):
        idxs = [rng.randrange(n) for _ in range(n)]
        sample_probs = [probs[i] for i in idxs]
        sample_labels = [labels[i] for i in idxs]
        if len({int(x) for x in sample_labels}) < 2:
            continue
        aucs.append(_roc_auc_pairwise(sample_probs, sample_labels))
    if not aucs:
        auc = _roc_auc_pairwise(probs, labels)
        return auc, auc
    aucs.sort()
    low_idx = max(0, int(len(aucs) * 0.025) - 1)
    high_idx = min(len(aucs) - 1, int(len(aucs) * 0.975))
    return aucs[low_idx], aucs[high_idx]


def evaluate_case(case: AcademicEvalCase) -> AcademicEvalResult:
    """Evaluate one academic benchmark case."""
    citation_fidelity = metric_citation_fidelity(case.generated_citations, case.verified_citations)
    claim_grounding = metric_claim_grounding(case.claims)
    abstract_body_consistency = metric_abstract_body_consistency(case.abstract_numbers, case.body_numbers)
    reviewer_rebuttal_completeness = metric_reviewer_rebuttal_completeness(case.reviewer_comment_ids, case.rebuttal_addressed_ids)
    venue_fit = metric_venue_fit(case.venue_checklist_items, case.venue_satisfied_items)
    cross_modality_synthesis = metric_cross_modality_synthesis(case.cross_modal_items_expected, case.cross_modal_items_used)
    long_horizon_consistency = metric_long_horizon_consistency(case.revision_terms, case.revision_numbers)

    metric_values = {
        "citation_fidelity": citation_fidelity,
        "claim_grounding": claim_grounding,
        "abstract_body_consistency": abstract_body_consistency,
        "reviewer_rebuttal_completeness": reviewer_rebuttal_completeness,
        "venue_fit": venue_fit,
        "cross_modality_synthesis": cross_modality_synthesis,
        "long_horizon_consistency": long_horizon_consistency,
    }
    weights = _resolve_metric_weights(case)
    overall = sum(float(metric_values[key]) * float(weights[key]) for key in _METRIC_KEYS)
    accept_prob = _score_to_accept_prob(overall)

    return AcademicEvalResult(
        case_id=case.case_id,
        citation_fidelity=citation_fidelity,
        claim_grounding=claim_grounding,
        abstract_body_consistency=abstract_body_consistency,
        reviewer_rebuttal_completeness=reviewer_rebuttal_completeness,
        venue_fit=venue_fit,
        cross_modality_synthesis=cross_modality_synthesis,
        long_horizon_consistency=long_horizon_consistency,
        overall_score=overall,
        metric_weights=weights,
        predicted_accept_prob=accept_prob,
        calibration_residual=0.0,
    )


def evaluate_dataset(cases: list[AcademicEvalCase]) -> AcademicEvalSummary:
    """Evaluate all cases and return aggregated summary."""
    if not cases:
        return AcademicEvalSummary(
            case_count=0,
            average_overall_score=0.0,
            average_citation_fidelity=0.0,
            average_claim_grounding=0.0,
            average_abstract_body_consistency=0.0,
            average_reviewer_rebuttal_completeness=0.0,
            average_venue_fit=0.0,
            average_cross_modality_synthesis=0.0,
            average_long_horizon_consistency=0.0,
            accepted_case_count=0,
            rejected_case_count=0,
            accepted_average_overall_score=0.0,
            rejected_average_overall_score=0.0,
            accept_reject_score_gap=0.0,
            label_ranking_accuracy=0.0,
            auc_accept_reject=0.0,
            ece=0.0,
            brier_score=0.0,
            safety_valve_triggered_count=0,
            safety_valve_triggered_rate=0.0,
            overall_score_ci_low=0.0,
            overall_score_ci_high=0.0,
            auc_ci_low=0.0,
            auc_ci_high=0.0,
            dynamic_weighting_enabled=True,
            calibration_bins=10,
            weighting_profiles={},
            benchmark_split="unspecified",
            source_name=None,
            results=[],
        )

    results = [evaluate_case(case) for case in cases]
    n = len(results)
    accepted_scores = [r.overall_score for c, r in zip(cases, results, strict=False) if c.decision == "accepted"]
    rejected_scores = [r.overall_score for c, r in zip(cases, results, strict=False) if c.decision == "rejected"]
    accepted_count = len(accepted_scores)
    rejected_count = len(rejected_scores)
    accepted_avg = _mean(accepted_scores)
    rejected_avg = _mean(rejected_scores)
    score_gap = accepted_avg - rejected_avg if accepted_count and rejected_count else 0.0

    pair_scores: list[float] = []
    if accepted_scores and rejected_scores:
        for acc, rej in product(accepted_scores, rejected_scores):
            if acc > rej:
                pair_scores.append(1.0)
            elif acc == rej:
                pair_scores.append(0.5)
            else:
                pair_scores.append(0.0)
    ranking_accuracy = _mean(pair_scores) if pair_scores else 0.0

    split_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    weighting_profiles: dict[str, dict[str, float]] = {}
    profile_counts: dict[str, int] = {}
    calibration_probs: list[float] = []
    calibration_labels: list[int] = []
    per_case_residuals: dict[str, float] = {}

    safety_valve_triggered_count = 0
    for case, result in zip(cases, results, strict=False):
        split = case.benchmark_split or "unspecified"
        split_counts[split] = split_counts.get(split, 0) + 1
        source = case.source_name or ""
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1

        profile_key = f"{case.domain or 'unknown'}::{case.venue or 'unknown'}"
        profile_counts[profile_key] = profile_counts.get(profile_key, 0) + 1
        if profile_key not in weighting_profiles:
            weighting_profiles[profile_key] = {metric: 0.0 for metric in _METRIC_KEYS}
        for metric in _METRIC_KEYS:
            weighting_profiles[profile_key][metric] += float(result.metric_weights.get(metric, 0.0))

        if case.decision in {"accepted", "rejected"}:
            label = 1 if case.decision == "accepted" else 0
            calibration_probs.append(float(result.predicted_accept_prob))
            calibration_labels.append(label)
            per_case_residuals[case.case_id] = float(result.predicted_accept_prob) - float(label)
        if bool(case.safety_valve_triggered):
            safety_valve_triggered_count += 1

    for key, count in profile_counts.items():
        if count <= 0:
            continue
        weighting_profiles[key] = {
            metric: float(weighting_profiles[key][metric]) / float(count)
            for metric in _METRIC_KEYS
        }

    auc = _roc_auc_pairwise(calibration_probs, calibration_labels)
    ece = _expected_calibration_error(calibration_probs, calibration_labels, bins=10)
    brier = (
        _mean([(float(prob) - float(label)) ** 2 for prob, label in zip(calibration_probs, calibration_labels, strict=False)])
        if calibration_probs and calibration_labels
        else 0.0
    )
    overall_ci_low, overall_ci_high = _bootstrap_mean_ci([row.overall_score for row in results])
    auc_ci_low, auc_ci_high = _bootstrap_auc_ci(calibration_probs, calibration_labels)
    for row in results:
        row.calibration_residual = float(per_case_residuals.get(row.case_id, 0.0))

    dominant_split = max(split_counts.items(), key=lambda x: x[1])[0] if split_counts else "unspecified"
    dominant_source = max(source_counts.items(), key=lambda x: x[1])[0] if source_counts else None

    return AcademicEvalSummary(
        case_count=n,
        average_overall_score=_mean([r.overall_score for r in results]),
        average_citation_fidelity=_mean([r.citation_fidelity for r in results]),
        average_claim_grounding=_mean([r.claim_grounding for r in results]),
        average_abstract_body_consistency=_mean([r.abstract_body_consistency for r in results]),
        average_reviewer_rebuttal_completeness=_mean([r.reviewer_rebuttal_completeness for r in results]),
        average_venue_fit=_mean([r.venue_fit for r in results]),
        average_cross_modality_synthesis=_mean([r.cross_modality_synthesis for r in results]),
        average_long_horizon_consistency=_mean([r.long_horizon_consistency for r in results]),
        accepted_case_count=accepted_count,
        rejected_case_count=rejected_count,
        accepted_average_overall_score=accepted_avg,
        rejected_average_overall_score=rejected_avg,
        accept_reject_score_gap=score_gap,
        label_ranking_accuracy=ranking_accuracy,
        auc_accept_reject=auc,
        ece=ece,
        brier_score=brier,
        safety_valve_triggered_count=safety_valve_triggered_count,
        safety_valve_triggered_rate=(float(safety_valve_triggered_count) / float(n)) if n > 0 else 0.0,
        overall_score_ci_low=overall_ci_low,
        overall_score_ci_high=overall_ci_high,
        auc_ci_low=auc_ci_low,
        auc_ci_high=auc_ci_high,
        dynamic_weighting_enabled=True,
        calibration_bins=10,
        weighting_profiles=weighting_profiles,
        benchmark_split=dominant_split,
        source_name=dominant_source,
        results=results,
    )
