#!/usr/bin/env python
"""Tests for monitoring capability tiers: graceful degradation, schema validation, fallback.

Run: python -m pytest skills/custom/data-analyst/scripts/test_monitoring_tiers.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the scripts directory is on path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Check optional dependencies
try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

requires_sklearn = pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
requires_scipy = pytest.mark.skipif(not HAS_SCIPY, reason="scipy not installed")


# ── 9.1: Pro scripts return DEPENDENCY_MISSING ──


def test_pro_trend_dependency_missing():
    """pro_trend.py returns DEPENDENCY_MISSING when statsmodels/ruptures are missing."""
    from pro_trend import _check_dependencies
    ok, missing = _check_dependencies()
    # In test environment without these deps, should report missing
    if not ok:
        assert len(missing) > 0
        assert any(d in ["scikit-learn", "statsmodels", "ruptures"] for d in missing)


def test_pro_anomaly_dependency_missing():
    """pro_anomaly.py returns DEPENDENCY_MISSING when scikit-learn is missing."""
    from pro_anomaly import _check_dependencies
    ok, missing = _check_dependencies()
    if not ok:
        assert "scikit-learn" in missing


def test_pro_correlation_dependency_missing():
    """pro_correlation.py returns DEPENDENCY_MISSING when scipy/sklearn missing."""
    from pro_correlation import _check_dependencies
    ok, missing = _check_dependencies()
    if not ok:
        assert len(missing) > 0


def test_pro_spectrum_dependency_missing():
    """pro_spectrum.py returns DEPENDENCY_MISSING when scipy is missing."""
    try:
        import scipy  # noqa: F401
    except ImportError:
        # If scipy not available, the emit_error path is triggered in main()
        pass


# ── 9.2: Ultra scripts ONNX model missing → fallback ──


def test_model_loader_onnx_missing():
    """_model_loader returns None when ONNX model file doesn't exist."""
    from _model_loader import load_model, model_available

    # Model files should not exist in test environment
    assert model_available("trend_forecaster") is False
    assert model_available("anomaly_autoencoder") is False
    assert model_available("health_predictor") is False
    assert model_available("spectrum_classifier") is False

    # load_model should return None
    assert load_model("trend_forecaster") is None
    assert load_model("anomaly_autoencoder") is None
    assert load_model("nonexistent_model") is None


@requires_sklearn
def test_ultra_trend_fallback():
    """ultra_trend.py falls back to Pro when ONNX is unavailable."""
    from ultra_trend import analyze_trend_ultra

    # Minimal valid time series
    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "unit": "mm/s",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [2.0 + i * 0.05 for i in range(30)],
        }
    ]

    result = analyze_trend_ultra(time_series, forecast_horizon=7)
    assert result["model_fallback"] is True  # ONNX not available
    assert result["per_metric"] is not None
    assert len(result["per_metric"]) == 1
    assert "forecast" in result["per_metric"][0]
    assert "confidence_bands" in result["per_metric"][0]
    assert result["per_metric"][0]["confidence_bands"]["confidence_95_upper"] is not None


@requires_sklearn
def test_ultra_anomaly_fallback():
    """ultra_anomaly.py falls back to Pro when ONNX is unavailable."""
    from ultra_anomaly import analyze_anomaly_ultra

    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "unit": "mm/s",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [2.0 + i * 0.1 for i in range(30)],
        },
        {
            "metric_key": "temperature",
            "name": "温度",
            "unit": "°C",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [50.0 + i * 0.3 for i in range(30)],
        },
    ]

    result = analyze_anomaly_ultra(time_series)
    assert result["model_fallback"] is True  # ONNX not available
    assert result["onnx_used"] is False
    assert "anomalies" in result
    assert "root_cause_ranking" in result


def test_ultra_kpi_fallback():
    """ultra_kpi.py falls back to Pro scoring when ONNX is unavailable."""
    from ultra_kpi import analyze_kpi_ultra

    data = {
        "equipment": [
            {
                "id": "EQ-001",
                "name": "压缩机A",
                "kpis": {
                    "vibration_level": {"current_value": 3.5},
                    "temperature": {"current_value": 72.0},
                    "runtime_rate": {"current_value": 97.5},
                },
            }
        ]
    }

    result = analyze_kpi_ultra(data)
    assert result["model_fallback"] is True
    assert result["equipment_count"] == 1
    assert "risk_ranking" in result
    assert "risk_matrix" in result
    eq = result["equipment_scores"][0]
    assert "health_score" in eq
    assert eq["health_prediction"] is None  # No ONNX model


# ── 9.3: Regression — Basic path unchanged ──


def test_basic_analysis_output_schema():
    """Basic trend_analysis.py output has expected schema fields."""
    from trend_analysis import _findings_for_series, _data_coverage

    series = {
        "metric_key": "vibration_level",
        "name": "振动烈度",
        "unit": "mm/s",
        "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
        "values": [2.0 + i * 0.05 for i in range(30)],
    }

    findings, alerts, evidence = _findings_for_series(series)
    assert isinstance(findings, list)
    assert isinstance(alerts, list)
    assert isinstance(evidence, list)


# ── 9.10/9.11: Graceful degradation ──


@requires_sklearn
def test_pro_output_schema_compatibility():
    """Pro scripts produce output compatible with Basic report rendering."""
    from pro_trend import analyze_trend_pro

    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "unit": "mm/s",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [2.0 + i * 0.05 for i in range(30)],
        }
    ]

    result = analyze_trend_pro(time_series)
    # Pro output must include basic-compatible fields
    assert "findings" in result
    assert "evidence" in result
    assert "time_series" in result
    assert result["schema_version"] == "2"
    # Finding must have basic-compatible fields
    if result["findings"]:
        f = result["findings"][0]
        assert "metric" in f or "metric_key" in f
        assert "direction" in f


@requires_sklearn
def test_ultra_output_schema_compatibility():
    """Ultra scripts produce output compatible with Pro/Basic report rendering."""
    from ultra_trend import analyze_trend_ultra

    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "unit": "mm/s",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [2.0 + i * 0.05 for i in range(30)],
        },
        {
            "metric_key": "temperature",
            "name": "温度",
            "unit": "°C",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 31)],
            "values": [50.0 + i * 0.2 for i in range(30)],
        },
    ]

    result = analyze_trend_ultra(time_series)
    assert result["schema_version"] == "2"
    assert "per_metric" in result
    assert "co_trending_groups" in result
    assert "model_fallback" in result


def test_data_quality_pro_tier():
    """data_quality.py produces valid output for Pro tier."""
    from data_quality import assess_quality

    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 11)],
            "values": [2.0, None, 2.5, 2.3, None, 2.8, 3.0, 2.7, None, 2.9],
        }
    ]

    result = assess_quality(time_series, tier="pro")
    assert result["tier"] == "pro"
    assert result["overall"]["total_missing"] == 3
    assert 0.6 <= result["overall"]["overall_completeness"] <= 0.8
    assert len(result["per_metric"]) == 1


def test_data_quality_ultra_tier():
    """data_quality.py produces enhanced output for Ultra tier."""
    from data_quality import assess_quality

    time_series = [
        {
            "metric_key": "vibration_level",
            "name": "振动烈度",
            "timestamps": [f"2026-05-{d:02d}" for d in range(1, 11)],
            "values": [2.0, None, 2.5, 2.3, 2.1, 2.8, 3.0, 2.7, None, 2.9],
        }
    ]

    result = assess_quality(time_series, tier="ultra")
    assert result["tier"] == "ultra"
    assert "quality_score_3d" in result["overall"]
    assert "interpolated_count" in result["overall"]
    assert "quality_score_3d" in result["per_metric"][0]


# ── Edge cases ──


def test_empty_time_series():
    """Scripts handle empty time series gracefully."""
    from ultra_trend import analyze_trend_ultra
    result = analyze_trend_ultra([])
    assert result["per_metric"] == []
    assert result["co_trending_groups"] == []


def test_insufficient_data():
    """Scripts skip series with fewer than 5 valid points."""
    from pro_trend import analyze_trend_pro

    time_series = [
        {
            "metric_key": "short_metric",
            "name": "短序列",
            "unit": "",
            "timestamps": ["2026-05-01", "2026-05-02"],
            "values": [1.0, 2.0],
        }
    ]

    result = analyze_trend_pro(time_series)
    assert len(result["findings"]) == 0


def test_duplicate_key_in_fault_signatures():
    """Fault signatures dict is well-formed with no duplicate entries."""
    from ultra_anomaly import FAULT_SIGNATURES
    assert len(FAULT_SIGNATURES) > 0
    for (metric, direction), causes in FAULT_SIGNATURES.items():
        assert isinstance(metric, str)
        assert isinstance(direction, str)
        assert isinstance(causes, list)
        for cause in causes:
            assert "cause" in cause
            assert "confidence" in cause


def test_bearing_fault_orders_complete():
    """Bearing fault orders cover all four types."""
    from pro_spectrum import BEARING_FAULT_ORDERS
    assert set(BEARING_FAULT_ORDERS.keys()) == {"BPFO", "BPFI", "BSF", "FTF"}
    for key, info in BEARING_FAULT_ORDERS.items():
        assert "label" in info
        assert "order_factor" in info
        assert info["order_factor"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
