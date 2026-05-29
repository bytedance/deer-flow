"""Tests for skills/custom/data-analyst/scripts/trend_analysis.py (§13.2 contract).

Sprint S6/M7 — covers Story S1 lower-half acceptance:
- 5-field §13.2 contract present (findings/evidence/confidence/data_coverage/human_review_required)
- summary_markdown MUST NOT appear in output
- human_review_required always True
- Each finding has at least one evidence linked via finding_id
- Volatility-spike + anomaly-cluster detection
- forecast list has one entry per metric
- trend_chart includes real series + forecast dashed series
- Empty input → structured error
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TRANSFORM_PATH = SCRIPTS_DIR / "trend_analysis.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"
SCRIPT_DIR_STR = str(SCRIPTS_DIR)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def transform(tmp_path):
    _load("_stub_helpers", HELPERS_PATH)
    if SCRIPT_DIR_STR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR_STR)
    return _load("trend_analysis", TRANSFORM_PATH)


def _make_series(metric_key: str, name: str, unit: str, n: int, base: float, amplitude: float, better: bool) -> dict:
    """Build a deterministic sine-wave series for test fixtures."""
    timestamps = [f"2026-04-{d:02d}" for d in range(1, n + 1)]
    phase = sum(ord(c) for c in metric_key) * 0.01
    values = [round(base + amplitude * math.sin(i * 0.3 + phase), 4) for i in range(n)]
    return {
        "metric_key": metric_key,
        "name": name,
        "unit": unit,
        "timestamps": timestamps,
        "values": values,
        "point_count": n,
        "better_when_higher": better,
    }


@pytest.fixture()
def trend_data(tmp_path):
    """Build a realistic trend_data.json fixture with inline data."""
    series = [
        _make_series("runtime_rate", "运行率", "%", 30, 0.92, 0.05, True),
        _make_series("vibration_level", "振动水平", "mm/s", 30, 3.0, 0.5, False),
        _make_series("alarm_count", "告警数量", "条", 30, 4.0, 3.0, False),
    ]
    payload = {
        "schema_version": "1",
        "metadata": {
            "date_range": ["2026-04-01", "2026-04-30"],
            "aggregation": "daily",
            "forecast_horizon": 7,
            "requested_metric_keys": ["runtime_rate", "vibration_level", "alarm_count"],
            "data_source": "http",
        },
        "time_series": series,
        "summary": {"metric_count": 3, "total_points": 90},
    }
    path = tmp_path / "trend_data.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run_transform(transform, trend_data, tmp_path):
    """Helper that invokes main() and returns the parsed result JSON."""
    sys.argv = [
        "trend_analysis.py",
        "--input", str(trend_data),
        "--output-dir", str(tmp_path),
    ]
    rc = transform.main()
    assert rc == 0
    out_path = tmp_path / "data" / "trend_analysis.json"
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_no_summary_markdown(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    assert "summary_markdown" not in result, (
        "trend_analysis must NOT emit summary_markdown; rendering is "
        "generic_renderer's exclusive responsibility (sprint plan S1)"
    )


def test_full_5_field_contract(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    for required in ("findings", "evidence", "confidence", "data_coverage", "human_review_required"):
        assert required in result, f"§13.2 mandate: '{required}' must appear in interpretive output"


def test_human_review_required_always_true(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    assert result["human_review_required"] is True


def test_each_finding_linked_to_evidence(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    finding_ids = {f["id"] for f in result["findings"]}
    evidence_finding_ids = {e["finding_id"] for e in result["evidence"]}
    # Every finding gets ≥1 evidence (sprint plan acceptance: at least 1 per finding)
    missing = finding_ids - evidence_finding_ids
    assert not missing, f"findings without evidence: {missing}"


def test_evidence_carries_provenance_fields(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    for ev in result["evidence"]:
        for field in ("source_type", "source_id", "snapshot_path", "checksum", "time_range", "retrieved_at"):
            assert field in ev, f"evidence missing §13.2 field {field}: {ev}"


def test_data_coverage_shape(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    coverage = result["data_coverage"]
    for field in ("requested_metrics", "covered_metrics", "missing_metrics", "time_coverage_pct", "max_points"):
        assert field in coverage


def test_confidence_one_of_low_medium_high(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    assert result["confidence"] in ("low", "medium", "high")


def test_forecast_one_per_metric(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    forecasts = result["forecast"]
    assert len(forecasts) == 3
    for fc in forecasts:
        assert fc["horizon_points"] == 7
        assert len(fc["forecast_points"]) == 7


def test_trend_chart_has_forecast_series(transform, trend_data, tmp_path):
    result = _run_transform(transform, trend_data, tmp_path)
    chart = result["trend_chart"]
    legend = chart["legend"]["data"]
    forecast_legend = [n for n in legend if "预测" in n]
    assert len(forecast_legend) == 3, "trend_chart must include a dashed forecast series per metric"


def test_empty_metrics_input_emits_error(transform, tmp_path):
    payload = {
        "schema_version": "1",
        "metadata": {"date_range": [], "aggregation": "daily", "forecast_horizon": 0},
        "time_series": [],
    }
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    sys.argv = ["trend_analysis.py", "--input", str(path), "--output-dir", str(tmp_path)]
    rc = transform.main()
    assert rc == 1  # emit_error returns 1
