"""Tests for commit/week online regression drift tracking."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.evals.academic.online_regression import (
    OnlineDriftThresholds,
    OnlineRegressionHistory,
    append_online_run,
    build_online_drift_report,
    build_online_run_from_offline_report,
    compare_online_runs,
    dump_online_regression_history,
    find_previous_commit_run,
    find_previous_week_run,
    load_online_regression_history,
    render_online_drift_markdown,
)


def _offline_report(
    *,
    status: str = "pass",
    core_auc: float = 1.0,
    core_ece: float = 0.16,
    core_brier: float = 0.04,
    core_overall: float = 0.82,
    core_gap: float = 0.62,
) -> dict:
    return {
        "status": status,
        "layers": {
            "core": {
                "status": status,
                "case_count": 8,
                "accepted_case_count": 4,
                "rejected_case_count": 4,
                "average_overall_score": core_overall,
                "auc_accept_reject": core_auc,
                "ece": core_ece,
                "brier_score": core_brier,
                "accept_reject_score_gap": core_gap,
            }
        },
    }


def test_online_history_load_dump_roundtrip(tmp_path: Path):
    history_path = tmp_path / "history.json"
    empty = load_online_regression_history(history_path)
    assert empty.runs == []

    run = build_online_run_from_offline_report(
        offline_report=_offline_report(),
        branch="main",
        commit_sha="abc123",
        created_at="2026-03-17T00:00:00Z",
    )
    updated = append_online_run(empty, run)
    dump_online_regression_history(history_path, updated)

    loaded = load_online_regression_history(history_path)
    assert loaded.schema_version == "deerflow.academic_online_regression.v1"
    assert len(loaded.runs) == 1
    assert loaded.runs[0].run_id == run.run_id
    # Ensure file is valid json payload.
    payload = json.loads(history_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "deerflow.academic_online_regression.v1"


def test_find_previous_commit_and_week_run():
    base_time = datetime(2026, 3, 10, tzinfo=UTC)
    run_old = build_online_run_from_offline_report(
        offline_report=_offline_report(),
        branch="main",
        commit_sha="sha-1",
        created_at=(base_time - timedelta(days=8)).isoformat(),
    )
    run_mid = build_online_run_from_offline_report(
        offline_report=_offline_report(),
        branch="main",
        commit_sha="sha-2",
        created_at=(base_time - timedelta(days=1)).isoformat(),
    )
    run_cur = build_online_run_from_offline_report(
        offline_report=_offline_report(),
        branch="main",
        commit_sha="sha-3",
        created_at=base_time.isoformat(),
    )
    history = OnlineRegressionHistory(updated_at=base_time.isoformat(), runs=[run_old, run_mid])
    assert find_previous_commit_run(history, run_cur).run_id == run_mid.run_id  # type: ignore[union-attr]
    assert find_previous_week_run(history, run_cur).run_id == run_old.run_id  # type: ignore[union-attr]


def test_compare_online_runs_detects_drift_alerts():
    previous = build_online_run_from_offline_report(
        offline_report=_offline_report(core_auc=0.98, core_ece=0.16, core_brier=0.04, core_overall=0.82, core_gap=0.60),
        branch="main",
        commit_sha="sha-prev",
        created_at="2026-03-10T00:00:00+00:00",
    )
    current = build_online_run_from_offline_report(
        offline_report=_offline_report(core_auc=0.90, core_ece=0.25, core_brier=0.10, core_overall=0.70, core_gap=0.50),
        branch="main",
        commit_sha="sha-cur",
        created_at="2026-03-17T00:00:00+00:00",
    )
    cmp_payload = compare_online_runs(
        current,
        previous,
        thresholds=OnlineDriftThresholds(
            max_auc_drop=0.03,
            max_ece_increase=0.04,
            max_brier_increase=0.04,
            max_overall_drop=0.05,
            max_score_gap_drop=0.05,
        ),
    )
    assert cmp_payload["status"] == "has_alerts"
    alert_names = {item["name"] for item in cmp_payload["alerts"]}
    assert "auc_drop" in alert_names
    assert "ece_increase" in alert_names
    assert "brier_increase" in alert_names
    assert "overall_score_drop" in alert_names
    assert "score_gap_drop" in alert_names


def test_build_online_drift_report_and_markdown():
    current = build_online_run_from_offline_report(
        offline_report=_offline_report(),
        branch="main",
        commit_sha="sha-cur",
        created_at="2026-03-17T00:00:00+00:00",
    )
    report = build_online_drift_report(
        current=current,
        previous_commit=None,
        previous_week=None,
        thresholds=OnlineDriftThresholds(),
    )
    assert report["status"] == "pass"
    assert report["comparisons"]["commit_to_previous"]["status"] == "insufficient_history"
    markdown = render_online_drift_markdown(report)
    assert "# Academic Online Regression Drift Report" in markdown
    assert "## `commit_to_previous`" in markdown

