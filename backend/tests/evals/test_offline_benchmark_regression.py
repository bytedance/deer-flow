"""Tests for offline benchmark regression gate runner."""

from __future__ import annotations

from src.evals.academic import (
    OfflineRegressionDriftThresholds,
    OfflineRegressionThresholds,
    build_offline_regression_drift_report,
    evaluate_offline_regression_layers,
    load_offline_layer_payloads,
    render_offline_regression_drift_markdown,
    render_offline_regression_markdown,
    write_offline_benchmark_layers,
)


def test_evaluate_offline_regression_layers_passes_on_default_suite(tmp_path):
    write_offline_benchmark_layers(tmp_path, overwrite=True)
    payloads = load_offline_layer_payloads(tmp_path)
    report = evaluate_offline_regression_layers(payloads, dataset_version="2026_03")

    assert report["status"] == "pass"
    assert report["layers"]["core"]["status"] == "pass"
    assert report["layers"]["failure_mode"]["status"] == "pass"
    assert report["layers"]["domain_ai_cs"]["status"] == "pass"
    assert report["layers"]["domain_biomed"]["status"] == "pass"
    assert report["layers"]["domain_cross_discipline"]["status"] == "pass"


def test_evaluate_offline_regression_layers_fails_when_threshold_too_strict(tmp_path):
    write_offline_benchmark_layers(tmp_path, overwrite=True)
    payloads = load_offline_layer_payloads(tmp_path)
    report = evaluate_offline_regression_layers(
        payloads,
        dataset_version="2026_03",
        thresholds=OfflineRegressionThresholds(core_min_auc=1.1),
    )

    assert report["status"] == "fail"
    failed_names = {item["name"] for item in report["failed_checks"]}
    assert "core_auc_accept_reject" in failed_names


def test_render_offline_regression_markdown_contains_layer_sections(tmp_path):
    write_offline_benchmark_layers(tmp_path, overwrite=True)
    payloads = load_offline_layer_payloads(tmp_path)
    report = evaluate_offline_regression_layers(payloads)
    markdown = render_offline_regression_markdown(report)

    assert "# Offline Benchmark Regression Report" in markdown
    assert "### `core`" in markdown
    assert "### `failure_mode`" in markdown
    assert "### `domain_ai_cs`" in markdown


def test_offline_regression_drift_gate_detects_hallucination_ece_brier_regression(tmp_path):
    write_offline_benchmark_layers(tmp_path, overwrite=True)
    payloads = load_offline_layer_payloads(tmp_path)
    baseline = evaluate_offline_regression_layers(payloads, dataset_version="2026_03")
    current = evaluate_offline_regression_layers(payloads, dataset_version="2026_04")
    # Simulate regressions on the core layer.
    current["layers"]["core"]["citation_hallucination_rate"] = baseline["layers"]["core"]["citation_hallucination_rate"] + 0.2
    current["layers"]["core"]["ece"] = baseline["layers"]["core"]["ece"] + 0.3
    current["layers"]["core"]["brier_score"] = baseline["layers"]["core"]["brier_score"] + 0.1

    drift = build_offline_regression_drift_report(
        current_report=current,
        baseline_report=baseline,
        thresholds=OfflineRegressionDriftThresholds(
            max_hallucination_rate_increase=0.0,
            max_ece_increase=0.0,
            max_brier_increase=0.0,
            max_auc_drop=1.0,
        ),
    )

    assert drift["status"] == "has_alerts"
    alert_names = {item["name"] for item in drift["alerts"]}
    assert "citation_hallucination_rate_increase" in alert_names
    assert "ece_increase" in alert_names
    assert "brier_score_increase" in alert_names


def test_render_offline_regression_drift_markdown_contains_layer_delta(tmp_path):
    write_offline_benchmark_layers(tmp_path, overwrite=True)
    payloads = load_offline_layer_payloads(tmp_path)
    baseline = evaluate_offline_regression_layers(payloads, dataset_version="2026_03")
    current = evaluate_offline_regression_layers(payloads, dataset_version="2026_04")
    drift = build_offline_regression_drift_report(
        current_report=current,
        baseline_report=baseline,
    )
    markdown = render_offline_regression_drift_markdown(drift)
    assert "# Offline Benchmark Drift Report" in markdown
    assert "## Layers" in markdown
    assert "### `core`" in markdown

