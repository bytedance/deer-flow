"""Unit tests for standalone daily-report script modules.

Tests _kpi_aggregator.py (all derivation methods, helpers, edge cases) and
_ins_client.py (point selection, mocked client calls, error handling).
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_PATH = Path(__file__).parent.parent.parent / "skills" / "custom" / "daily-report" / "scripts"


def _load_script_module(name: str):
    file_path = _SCRIPTS_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _script_sandbox(*names: str):
    """Load script modules, register in sys.modules, cleanup on exit."""
    saved = {n: sys.modules.get(n) for n in names}
    modules = {}
    try:
        for n in names:
            mod = _load_script_module(n)
            sys.modules[n] = mod
            modules[n] = mod
        yield modules
    finally:
        for n, orig in saved.items():
            if orig is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = orig


# ═══════════════════════════════════════════════════════════════════════════
# _kpi_aggregator.py tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """Tests for _row_value, _row_first_value, _row_time_ms, _resolve_alarm_threshold."""

    def test_row_value_from_values_dict(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_value
            row = {"time_ms": 1000, "values": {"speed": 123.5}}
            assert f(row, "speed") == 123.5

    def test_row_value_from_flat_row(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_value
            assert f({"speed": 99.9}, "speed") == 99.9

    def test_row_value_none_for_missing(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_value
            assert f({"values": {"temp": 45}}, "speed") is None

    def test_row_value_none_for_nan(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_value
            assert f({"values": {"speed": float("nan")}}, "speed") is None

    def test_row_first_value_returns_first_non_null(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_first_value
            row = {"values": {"v_rms": None, "velocity": 5.5}}
            assert f(row, ["v_rms", "velocity"]) == 5.5

    def test_row_time_ms_fallbacks(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._row_time_ms
            assert f({"time_ms": 1700000000000}) == 1700000000000
            assert f({"datatime": 1700000000000}) == 1700000000000
            assert f({"time": "1700000000000"}) == 1700000000000
            assert f({"values": {"speed": 10}}) is None

    def test_resolve_alarm_threshold_8k_fallbacks(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"]._resolve_alarm_threshold
            # tier C falls back to h_alarm for 8k
            assert f({"endpoint_series": "8k", "h_alarm": 15.0}, "pp_value", "C") == 15.0
            # tier D falls back to hh_alarm for 8k
            assert f({"endpoint_series": "8k", "hh_alarm": 25.0}, "pp_value", "D") == 25.0
            # string threshold
            assert f({"alarm_thresholds": {"pp_value": {"C": "20.5"}}}, "pp_value", "C") == 20.5


class TestDerivationMean:
    def test_basic_mean(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"v_rms": 5.0}},
                {"values": {"v_rms": 10.0}},
                {"values": {"v_rms": 15.0}},
            ]
            assert f(rows, "vibration_velocity_rms") == 10.0

    def test_skips_none(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"v_rms": 5.0}},
                {"values": {"v_rms": None}},
                {"values": {"v_rms": 15.0}},
            ]
            assert f(rows, "vibration_velocity_rms") == 10.0

    def test_empty_returns_none(self):
        with _script_sandbox("_kpi_aggregator") as m:
            assert m["_kpi_aggregator"].aggregate_trend_to_kpi([], "vibration_velocity_rms") is None

    def test_applies_value_scale(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"value": 5000}},
                {"values": {"value": 6000}},
            ]
            assert f(rows, "bearing_temp") == 55.0  # (5000+6000)/2 * 0.01


class TestDerivationRuntimeRate:
    def test_fraction_running(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"speed": 100}},
                {"values": {"speed": 0}},
                {"values": {"speed": 150}},
                {"values": {"speed": 0}},
            ]
            assert f(rows, "runtime_rate") == 0.5

    def test_all_running(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            assert f([{"values": {"speed": 100}}, {"values": {"speed": 200}}], "runtime_rate") == 1.0

    def test_all_stopped(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            assert f([{"values": {"speed": 0}}, {"values": {"speed": 0}}], "runtime_rate") == 0.0


class TestDerivationDowntimeCount:
    def test_counts_falling_edges(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"speed": 100}},
                {"values": {"speed": 0}},   # falling edge
                {"values": {"speed": 150}},
                {"values": {"speed": 0}},   # falling edge
            ]
            assert f(rows, "downtime_count") == 2

    def test_no_falling_edges(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [{"values": {"speed": 0}}, {"values": {"speed": 100}}]
            assert f(rows, "downtime_count") == 0


class TestDerivationAlarmCount:
    def test_counts_exceeding_threshold(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"pp_value": 15.0}},
                {"values": {"pp_value": 25.0}},
                {"values": {"pp_value": 30.0}},
            ]
            point_meta = {"alarm_thresholds": {"pp_value": {"C": 20.0}}}
            assert f(rows, "alarm_count", point_meta) == 2

    def test_returns_zero_without_meta(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            assert f([{"values": {"pp_value": 25.0}}], "alarm_count", None) == 0


class TestDerivationThicknessLoss:
    def test_first_minus_last(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            rows = [
                {"values": {"thickness": 10.5}},
                {"values": {"thickness": 10.2}},
                {"values": {"thickness": 9.8}},
            ]
            assert f(rows, "thickness_loss") == 0.7

    def test_single_sample_returns_zero(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            assert f([{"values": {"thickness": 10.5}}], "thickness_loss") == 0.0


class TestHourlyRuntimeRate:
    def test_24_buckets(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].hourly_runtime_rate
            assert len(f([])) == 24
            assert f([]) == [0.0] * 24

    def test_buckets_by_hour(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].hourly_runtime_rate
            # hour 10: 3 running, 1 stopped = 0.75
            base = 1700000000000  # some timestamp
            from datetime import datetime
            base = int(datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000)
            rows = [
                {"time_ms": base, "values": {"speed": 100}},
                {"time_ms": base + 60000, "values": {"speed": 100}},
                {"time_ms": base + 120000, "values": {"speed": 0}},
                {"time_ms": base + 180000, "values": {"speed": 100}},
            ]
            result = f(rows)
            assert result[10] == 0.75
            assert all(result[i] == 0.0 for i in range(24) if i != 10)


class TestAggregateEquipmentKpis:
    def test_multi_equipment(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_equipment_kpis
            trend = {
                "EQ1": [
                    {"time_ms": 1000, "values": {"speed": 100}},
                    {"time_ms": 2000, "values": {"speed": 0}},
                ],
                "EQ2": [
                    {"time_ms": 1000, "values": {"speed": 100}},
                    {"time_ms": 2000, "values": {"speed": 100}},
                ],
            }
            kpis, union = f(trend, ["runtime_rate"], {})
            assert kpis["EQ1"]["runtime_rate"] == 0.5
            assert kpis["EQ2"]["runtime_rate"] == 1.0
            assert len(union) == 4

    def test_unknown_kpi_key_is_none(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_equipment_kpis
            kpis, union = f({"EQ1": [{"values": {"speed": 100}}]}, ["no_such_kpi"], {})
            assert kpis["EQ1"]["no_such_kpi"] is None


class TestKpiAggregatorEdgeCases:
    def test_unknown_kpi_raises(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            with pytest.raises(ValueError, match="unmappable KPI key"):
                f([{"values": {"speed": 100}}], "unknown_kpi")

    def test_feature_aliases(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].aggregate_trend_to_kpi
            # bearing_temp aliases include "temperature"
            assert f([{"values": {"temperature": 5000}}], "bearing_temp") == 50.0

    def test_compute_hourly_runtime_rate_wrapper(self):
        with _script_sandbox("_kpi_aggregator") as m:
            f = m["_kpi_aggregator"].compute_hourly_runtime_rate
            result = f([])
            assert len(result) == 24
            assert result == [0.0] * 24


# ═══════════════════════════════════════════════════════════════════════════
# _ins_client.py tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSelectPointsBySeries:
    def test_selects_matching_series(self):
        with _script_sandbox("_ins_client") as m:
            f = m["_ins_client"]._select_points_by_series
            components = [
                {"id": "p1", "endpoint_series": "8k"},
                {"id": "p2", "endpoint_series": "2k"},
                {"id": "p3", "endpoint_series": "8k"},
            ]
            selected = f(components, "8k")
            assert sorted(p["id"] for p in selected) == ["p1", "p3"]

    def test_skips_children_when_series_set(self):
        with _script_sandbox("_ins_client") as m:
            f = m["_ins_client"]._select_points_by_series
            components = [
                {
                    "id": "parent",
                    "endpoint_series": "8k",
                    "children": [{"id": "child", "endpoint_series": "8k"}],
                },
            ]
            selected = f(components, "8k")
            assert [p["id"] for p in selected] == ["parent"]

    def test_traverses_nested_children(self):
        with _script_sandbox("_ins_client") as m:
            f = m["_ins_client"]._select_points_by_series
            components = [
                {
                    "id": "g1",
                    "children": [
                        {"id": "c1", "endpoint_series": "8k"},
                    ],
                },
                {
                    "id": "g2",
                    "points": [
                        {"id": "p1", "endpoint_series": "8k"},
                    ],
                },
            ]
            selected = f(components, "8k")
            ids = [p["id"] for p in selected]
            assert "c1" in ids
            assert "p1" in ids

    def test_handles_non_dict_nodes(self):
        with _script_sandbox("_ins_client") as m:
            f = m["_ins_client"]._select_points_by_series
            components = ["not_a_dict", 42, None]
            selected = f(components, "8k")
            assert selected == []


class TestInsClientAvailability:
    def test_is_available_returns_bool(self):
        with _script_sandbox("_ins_client") as m:
            # Without features-tool installed, should return False
            result = m["_ins_client"].is_available()
            assert isinstance(result, bool)

    def test_get_availability_reason_returns_string(self):
        with _script_sandbox("_ins_client") as m:
            result = m["_ins_client"].get_availability_reason()
            assert isinstance(result, str)


class TestInsClientFetchTrendData:
    def test_fetches_trend_with_mocked_client(self):
        mock_rows = [
            {"time_ms": 1000, "values": {"speed": 100}},
            {"time_ms": 2000, "values": {"speed": 0}},
        ]
        mock_client = MagicMock()
        mock_client.get_slim_components.return_value = [
            {"id": "pt1", "endpoint_series": "8k"},
        ]
        mock_client.get_trend_data.return_value = mock_rows

        with _script_sandbox("_ins_client") as m:
            with patch.object(m["_ins_client"], "_get_client", return_value=mock_client):
                result = m["_ins_client"].fetch_trend_data(
                    ["EQ1"], "2026-05-15T00:00:00", "2026-05-15T23:59:59", "rotating_machinery",
                )
        assert "EQ1" in result
        assert len(result["EQ1"]) == 2

    def test_handles_get_components_error(self):
        mock_client = MagicMock()
        mock_client.get_slim_components.side_effect = RuntimeError("API down")

        with _script_sandbox("_ins_client") as m:
            with patch.object(m["_ins_client"], "_get_client", return_value=mock_client):
                result = m["_ins_client"].fetch_trend_data(
                    ["EQ1"], "2026-05-15T00:00:00", "2026-05-15T23:59:59",
                )
        assert result["EQ1"] == []

    def test_handles_no_matching_points(self):
        mock_client = MagicMock()
        mock_client.get_slim_components.return_value = [
            {"id": "pt1", "endpoint_series": "2k"},  # wrong series for rotating
        ]

        with _script_sandbox("_ins_client") as m:
            with patch.object(m["_ins_client"], "_get_client", return_value=mock_client):
                result = m["_ins_client"].fetch_trend_data(
                    ["EQ1"], "2026-05-15T00:00:00", "2026-05-15T23:59:59", "rotating_machinery",
                )
        assert result["EQ1"] == []


class TestInsClientFetchAlarms:
    def test_fetches_alarms_with_mocked_client(self):
        mock_client = MagicMock()
        mock_client.get_machine_drops.return_value = [
            {"time": "2026-05-15T10:00:00", "eventType": 1, "eventName": "振动报警"},
        ]

        with _script_sandbox("_ins_client") as m:
            with patch.object(m["_ins_client"], "_get_client", return_value=mock_client):
                result = m["_ins_client"].fetch_alarm_events(
                    ["EQ1"], "2026-05-15T00:00:00", "2026-05-15T23:59:59",
                )
        assert len(result) == 1
        assert result[0]["equipment"] == "EQ1"
        assert result[0]["level"] == "high"

    def test_handles_alarm_error(self):
        mock_client = MagicMock()
        mock_client.get_machine_drops.side_effect = RuntimeError("API down")

        with _script_sandbox("_ins_client") as m:
            with patch.object(m["_ins_client"], "_get_client", return_value=mock_client):
                result = m["_ins_client"].fetch_alarm_events(
                    ["EQ1"], "2026-05-15T00:00:00", "2026-05-15T23:59:59",
                )
        assert result == []

    def test_event_level_mapping(self):
        with _script_sandbox("_ins_client") as m:
            f = m["_ins_client"]._event_level
            assert f(1) == "high"
            assert f(2) == "warning"
            assert f(3) == "info"
            assert f(14) == "warning"
            assert f(15) == "high"
            assert f(99) == "info"  # unknown defaults to info
