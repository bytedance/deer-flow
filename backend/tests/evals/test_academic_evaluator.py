"""Tests for academic evaluation framework."""

from __future__ import annotations

from pathlib import Path

from src.evals.academic import (
    evaluate_case,
    evaluate_dataset,
    evaluate_failure_mode_library,
    load_builtin_eval_cases,
    load_eval_cases,
)
from src.evals.academic.schemas import AcademicEvalCase


def test_load_eval_cases_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "academic_benchmark_cases.json"
    cases = load_eval_cases(fixture_path)
    assert len(cases) == 20
    assert cases[0].case_id == "bio-01"
    assert cases[-1].case_id == "ai-10"


def test_evaluate_case_range():
    case = AcademicEvalCase(
        case_id="unit-1",
        domain="ai_cs",
        venue="NeurIPS",
        generated_citations=["10.1/a"],
        verified_citations=["10.1/a"],
        claims=[{"type": "strong", "has_evidence": True, "has_citation": True}],
        abstract_numbers=[0.9],
        body_numbers=[0.9],
        reviewer_comment_ids=["R1"],
        rebuttal_addressed_ids=["R1"],
        venue_checklist_items=["ablation", "baseline"],
        venue_satisfied_items=["ablation", "baseline"],
        cross_modal_items_expected=2,
        cross_modal_items_used=2,
        revision_terms=[["ablation", "baseline"], ["ablation", "baseline"]],
        revision_numbers=[[0.9], [0.9]],
    )
    result = evaluate_case(case)
    assert 0.0 <= result.overall_score <= 1.0
    assert result.citation_fidelity == 1.0


def test_evaluate_dataset_summary():
    fixture_path = Path(__file__).parent / "fixtures" / "academic_benchmark_cases.json"
    cases = load_eval_cases(fixture_path)
    summary = evaluate_dataset(cases)
    assert summary.case_count == 20
    assert len(summary.results) == 20
    assert 0.0 <= summary.average_overall_score <= 1.0

    best = max(summary.results, key=lambda r: r.overall_score)
    worst = min(summary.results, key=lambda r: r.overall_score)
    assert best.overall_score >= worst.overall_score


def test_load_builtin_accept_reject_dataset():
    cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    assert len(cases) == 8
    decisions = {case.decision for case in cases}
    assert {"accepted", "rejected"}.issubset(decisions)
    assert all(case.benchmark_split == "top_tier_accept_reject_v1" for case in cases)


def test_accept_reject_separation_metrics():
    cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    summary = evaluate_dataset(cases)
    assert summary.accepted_case_count > 0
    assert summary.rejected_case_count > 0
    assert 0.0 <= summary.label_ranking_accuracy <= 1.0
    # In the curated benchmark, accepted papers should score higher on average.
    assert summary.accept_reject_score_gap > 0.0


def test_evaluate_dataset_reports_calibration_and_confidence_interval():
    cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    summary = evaluate_dataset(cases)
    assert 0.0 <= summary.auc_accept_reject <= 1.0
    assert 0.0 <= summary.ece <= 1.0
    assert summary.brier_score >= 0.0
    assert summary.overall_score_ci_low <= summary.average_overall_score <= summary.overall_score_ci_high
    assert summary.auc_ci_low <= summary.auc_accept_reject <= summary.auc_ci_high
    assert summary.weighting_profiles
    assert summary.results
    assert all(0.0 <= result.predicted_accept_prob <= 1.0 for result in summary.results)


def test_failure_mode_library_builtin_dataset_gate_pass():
    cases = load_builtin_eval_cases("failure_mode_library_v1")
    report = evaluate_failure_mode_library(cases)
    assert report["status"] == "pass"
    assert report["targeted_case_count"] >= 7
