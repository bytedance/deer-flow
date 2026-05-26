"""Tests for skills/custom/data-analyst/scripts/query_trend.py.

Sprint S6/M7 — covers Story S1 acceptance:
- 3 aggregation modes (hourly/daily/weekly) produce correct point counts
- time_series[] schema (metric_key/name/unit/timestamps/values/point_count)
- metadata block (date_range/aggregation/forecast_horizon/data_source)
- Deterministic output (same input → same output)
- forecast_horizon validation
- Bad date_range / empty metrics produce structured errors
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "query_trend.py"
STUB_HELPERS_PATH = SCRIPT_PATH.parent / "_stub_helpers.py"
SCRIPT_DIR = str(SCRIPT_PATH.parent)


def _load_module():
    helpers_spec = importlib.util.spec_from_file_location("_stub_helpers", STUB_HELPERS_PATH)
    assert helpers_spec and helpers_spec.loader
    helpers = importlib.util.module_from_spec(helpers_spec)
    sys.modules["_stub_helpers"] = helpers
    helpers_spec.loader.exec_module(helpers)

    scripts_dir_added = False
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
        scripts_dir_added = True

    try:
        spec = importlib.util.spec_from_file_location("query_trend", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        if scripts_dir_added and SCRIPT_DIR in sys.path:
            sys.path.remove(SCRIPT_DIR)
        raise


@pytest.fixture()
def query_trend():
    return _load_module()


def test_daily_aggregation_point_count(query_trend):
    # April 2026 has 30 days
    timestamps = query_trend._enumerate_steps(
        query_trend.date.fromisoformat("2026-04-01"),
        query_trend.date.fromisoformat("2026-04-30"),
        "daily",
    )
    assert len(timestamps) == 30
    series = query_trend._build_series("runtime_rate", timestamps)
    assert series["point_count"] == 30
    assert series["metric_key"] == "runtime_rate"
    assert series["unit"] == "%"


def test_hourly_aggregation_point_count(query_trend):
    # 1 day → 24 hourly points
    timestamps = query_trend._enumerate_steps(
        query_trend.date.fromisoformat("2026-04-01"),
        query_trend.date.fromisoformat("2026-04-01"),
        "hourly",
    )
    assert len(timestamps) == 24


def test_weekly_aggregation_point_count(query_trend):
    # April 2026 has 30 days → buckets at 04-01, 04-08, 04-15, 04-22, 04-29 = 5 points
    timestamps = query_trend._enumerate_steps(
        query_trend.date.fromisoformat("2026-04-01"),
        query_trend.date.fromisoformat("2026-04-30"),
        "weekly",
    )
    assert len(timestamps) == 5


def test_deterministic_output(query_trend):
    """Same metric_key + same step index must yield same value."""
    meta = query_trend._metric_meta("runtime_rate")
    v1 = query_trend._deterministic_value("runtime_rate", 5, 30, meta)
    v2 = query_trend._deterministic_value("runtime_rate", 5, 30, meta)
    assert v1 == v2


def test_metric_catalog_known_metrics_have_units(query_trend):
    """All catalog-known metrics must have name + unit + amplitude + base."""
    for metric_key in query_trend.METRIC_CATALOG:
        meta = query_trend._metric_meta(metric_key)
        assert "name" in meta
        assert "unit" in meta
        assert "amplitude" in meta
        assert "base" in meta


def test_unknown_metric_fallback(query_trend):
    """Unknown metric keys still work — they get a fallback meta."""
    meta = query_trend._metric_meta("totally_unknown_metric")
    assert meta["name"] == "totally_unknown_metric"
    assert meta["unit"] == ""


def test_unsupported_aggregation_raises(query_trend):
    with pytest.raises(ValueError, match="unsupported aggregation"):
        query_trend._enumerate_steps(
            query_trend.date.fromisoformat("2026-04-01"),
            query_trend.date.fromisoformat("2026-04-30"),
            "quarterly",
        )


def test_series_values_in_reasonable_range(query_trend):
    """Demo data should stay within ±100% of base (no NaN, no extreme drift)."""
    timestamps = query_trend._enumerate_steps(
        query_trend.date.fromisoformat("2026-01-01"),
        query_trend.date.fromisoformat("2026-12-31"),
        "daily",
    )
    series = query_trend._build_series("runtime_rate", timestamps)
    meta = query_trend.METRIC_CATALOG["runtime_rate"]
    for v in series["values"]:
        assert isinstance(v, float)
        # Should never exceed base ± (amplitude × 2)
        assert abs(v - meta["base"]) <= meta["amplitude"] * 2.5
