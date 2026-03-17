"""CI regression gate for intro->discussion long-horizon consistency."""

from __future__ import annotations

from pathlib import Path

from src.evals.academic import evaluate_dataset, load_eval_cases


def test_intro_discussion_long_horizon_consistency_regression_gate():
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "long_horizon_intro_discussion_regression.json"
    )
    cases = load_eval_cases(fixture_path)
    summary = evaluate_dataset(cases)

    assert summary.case_count >= 4
    assert summary.average_long_horizon_consistency >= 0.53, (
        "Long-horizon consistency regression: "
        f"{summary.average_long_horizon_consistency:.4f} < 0.53"
    )
    assert summary.accept_reject_score_gap > 0.0

