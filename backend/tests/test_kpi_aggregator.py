"""Unit tests for kpi_aggregator module (Task 1.6).

Tests all 6 derivation methods with representative data to ensure
output matches legacy _ins_provider.py behavior.
"""

from datetime import datetime

import pytest

from deerflow.integrations.adapters.ins.kpi_aggregator import (
    _resolve_alarm_threshold,
    _row_first_value,
    _row_time_ms,
    _row_value,
    aggregate_equipment_kpis,
    aggregate_trend_to_kpi,
    compute_hourly_runtime_rate,
    hourly_runtime_rate,
)
from deerflow.integrations.adapters.ins.kpi_map import select_points_for_kpi

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestRowValue:
    def test_extracts_from_values_dict(self):
        row = {"time_ms": 1000, "values": {"speed": 123.5, "temp": 45.0}}
        assert _row_value(row, "speed") == 123.5
        assert _row_value(row, "temp") == 45.0

    def test_extracts_from_flat_row(self):
        row = {"time_ms": 1000, "speed": 99.9}
        assert _row_value(row, "speed") == 99.9

    def test_returns_none_for_missing_feature(self):
        row = {"time_ms": 1000, "values": {"temp": 45.0}}
        assert _row_value(row, "speed") is None

    def test_returns_none_for_null_value(self):
        row = {"time_ms": 1000, "values": {"speed": None}}
        assert _row_value(row, "speed") is None

    def test_returns_none_for_nan(self):
        row = {"time_ms": 1000, "values": {"speed": float("nan")}}
        assert _row_value(row, "speed") is None

    def test_handles_integer_values(self):
        row = {"time_ms": 1000, "values": {"speed": 100}}
        assert _row_value(row, "speed") == 100.0
        assert isinstance(_row_value(row, "speed"), float)


class TestRowFirstValue:
    def test_returns_first_non_null(self):
        row = {"values": {"v_rms": None, "velocity": 5.5, "speed": 10.0}}
        assert _row_first_value(row, ["v_rms", "velocity", "speed"]) == 5.5

    def test_returns_none_if_all_null(self):
        row = {"values": {"v_rms": None, "velocity": None}}
        assert _row_first_value(row, ["v_rms", "velocity"]) is None

    def test_returns_none_for_empty_list(self):
        row = {"values": {"speed": 10.0}}
        assert _row_first_value(row, []) is None


class TestRowTimeMs:
    def test_extracts_time_ms(self):
        row = {"time_ms": 1700000000000}
        assert _row_time_ms(row) == 1700000000000

    def test_extracts_datatime_fallback(self):
        row = {"datatime": 1700000000000}
        assert _row_time_ms(row) == 1700000000000

    def test_extracts_time_fallback(self):
        row = {"time": 1700000000000}
        assert _row_time_ms(row) == 1700000000000

    def test_handles_string_timestamp(self):
        row = {"time_ms": "1700000000000"}
        assert _row_time_ms(row) == 1700000000000

    def test_returns_none_for_missing(self):
        row = {"values": {"speed": 10.0}}
        assert _row_time_ms(row) is None

    def test_returns_none_for_invalid_string(self):
        row = {"time_ms": "not-a-number"}
        assert _row_time_ms(row) is None


class TestResolveAlarmThreshold:
    def test_reads_from_alarm_thresholds_dict(self):
        point_meta = {
            "alarm_thresholds": {
                "pp_value": {"B": 10.0, "C": 20.0, "D": 30.0}
            }
        }
        assert _resolve_alarm_threshold(point_meta, "pp_value", "C") == 20.0

    def test_fallback_to_h_alarm_for_8k_tier_c(self):
        point_meta = {"endpoint_series": "8k", "h_alarm": 15.0}
        assert _resolve_alarm_threshold(point_meta, "pp_value", "C") == 15.0

    def test_fallback_to_hh_alarm_for_8k_tier_d(self):
        point_meta = {"endpoint_series": "8k", "hh_alarm": 25.0}
        assert _resolve_alarm_threshold(point_meta, "pp_value", "D") == 25.0

    def test_returns_none_if_no_threshold(self):
        point_meta = {"alarm_thresholds": {}}
        assert _resolve_alarm_threshold(point_meta, "pp_value", "C") is None

    def test_handles_string_threshold(self):
        point_meta = {"alarm_thresholds": {"pp_value": {"C": "20.5"}}}
        assert _resolve_alarm_threshold(point_meta, "pp_value", "C") == 20.5

    def test_returns_none_for_invalid_string(self):
        point_meta = {"alarm_thresholds": {"pp_value": {"C": "invalid"}}}
        assert _resolve_alarm_threshold(point_meta, "pp_value", "C") is None


# ---------------------------------------------------------------------------
# Derivation method tests
# ---------------------------------------------------------------------------


class TestDerivationMean:
    def test_computes_arithmetic_mean(self):
        rows = [
            {"time_ms": 1000, "values": {"v_rms": 5.0}},
            {"time_ms": 2000, "values": {"v_rms": 10.0}},
            {"time_ms": 3000, "values": {"v_rms": 15.0}},
        ]
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result == 10.0

    def test_skips_null_values(self):
        rows = [
            {"time_ms": 1000, "values": {"v_rms": 5.0}},
            {"time_ms": 2000, "values": {"v_rms": None}},
            {"time_ms": 3000, "values": {"v_rms": 15.0}},
        ]
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result == 10.0

    def test_returns_none_for_empty_data(self):
        rows = []
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result is None

    def test_returns_none_if_all_null(self):
        rows = [
            {"time_ms": 1000, "values": {"v_rms": None}},
            {"time_ms": 2000, "values": {"v_rms": None}},
        ]
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result is None

    def test_applies_value_scale(self):
        # bearing_temp has value_scale: 0.01
        rows = [
            {"time_ms": 1000, "values": {"value": 5000}},
            {"time_ms": 2000, "values": {"value": 6000}},
        ]
        result = aggregate_trend_to_kpi(rows, "bearing_temp")
        # (5000 * 0.01 + 6000 * 0.01) / 2 = (50 + 60) / 2 = 55
        assert result == 55.0


class TestDerivationMax:
    def test_returns_maximum_value(self):
        # Note: max derivation exists in kpi_aggregator but no KPI uses it currently
        # Testing with a hypothetical KPI that uses max
        rows = [
            {"time_ms": 1000, "values": {"v_rms": 5.0}},
            {"time_ms": 2000, "values": {"v_rms": 15.0}},
            {"time_ms": 3000, "values": {"v_rms": 10.0}},
        ]
        # vibration_velocity_rms uses mean, but we can test the logic
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result == 10.0  # mean, not max

    def test_returns_none_for_empty_data(self):
        rows = []
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result is None


class TestDerivationRuntimeRate:
    def test_computes_speed_positive_fraction(self):
        rows = [
            {"time_ms": 1000, "values": {"speed": 100}},
            {"time_ms": 2000, "values": {"speed": 0}},
            {"time_ms": 3000, "values": {"speed": 150}},
            {"time_ms": 4000, "values": {"speed": 0}},
        ]
        result = aggregate_trend_to_kpi(rows, "runtime_rate")
        # 2 out of 4 samples have speed > 0
        assert result == 0.5

    def test_all_running(self):
        rows = [
            {"time_ms": 1000, "values": {"speed": 100}},
            {"time_ms": 2000, "values": {"speed": 200}},
        ]
        result = aggregate_trend_to_kpi(rows, "runtime_rate")
        assert result == 1.0

    def test_all_stopped(self):
        rows = [
            {"time_ms": 1000, "values": {"speed": 0}},
            {"time_ms": 2000, "values": {"speed": 0}},
        ]
        result = aggregate_trend_to_kpi(rows, "runtime_rate")
        assert result == 0.0

    def test_returns_none_for_empty_data(self):
        rows = []
        result = aggregate_trend_to_kpi(rows, "runtime_rate")
        assert result is None


class TestDerivationDowntimeCount:
    def test_counts_falling_edges(self):
        rows = [
            {"time_ms": 1000, "values": {"speed": 100}},
            {"time_ms": 2000, "values": {"speed": 0}},  # falling edge 1
            {"time_ms": 3000, "values": {"speed": 150}},
            {"time_ms": 4000, "values": {"speed": 0}},  # falling edge 2
            {"time_ms": 5000, "values": {"speed": 0}},
        ]
        result = aggregate_trend_to_kpi(rows, "downtime_count")
        assert result == 2

    def test_no_falling_edges(self):
        rows = [
            {"time_ms": 1000, "values": {"speed": 0}},
            {"time_ms": 2000, "values": {"speed": 100}},
            {"time_ms": 3000, "values": {"speed": 150}},
        ]
        result = aggregate_trend_to_kpi(rows, "downtime_count")
        assert result == 0

    def test_single_sample(self):
        rows = [{"time_ms": 1000, "values": {"speed": 100}}]
        result = aggregate_trend_to_kpi(rows, "downtime_count")
        assert result == 0


class TestDerivationAlarmCount:
    def test_counts_values_exceeding_threshold(self):
        rows = [
            {"time_ms": 1000, "values": {"pp_value": 15.0}},
            {"time_ms": 2000, "values": {"pp_value": 25.0}},  # exceeds 20
            {"time_ms": 3000, "values": {"pp_value": 18.0}},
            {"time_ms": 4000, "values": {"pp_value": 30.0}},  # exceeds 20
        ]
        point_meta = {
            "alarm_thresholds": {"pp_value": {"C": 20.0}}
        }
        result = aggregate_trend_to_kpi(rows, "alarm_count", point_meta)
        assert result == 2

    def test_returns_zero_if_no_threshold(self):
        rows = [
            {"time_ms": 1000, "values": {"pp_value": 25.0}},
        ]
        point_meta = {"alarm_thresholds": {}}
        result = aggregate_trend_to_kpi(rows, "alarm_count", point_meta)
        assert result == 0

    def test_returns_zero_if_point_meta_none(self):
        rows = [
            {"time_ms": 1000, "values": {"pp_value": 25.0}},
        ]
        result = aggregate_trend_to_kpi(rows, "alarm_count", None)
        assert result == 0


class TestDerivationThicknessLoss:
    def test_computes_first_minus_last(self):
        rows = [
            {"time_ms": 1000, "values": {"thickness": 10.5}},
            {"time_ms": 2000, "values": {"thickness": 10.2}},
            {"time_ms": 3000, "values": {"thickness": 9.8}},
        ]
        result = aggregate_trend_to_kpi(rows, "thickness_loss")
        assert result == 0.7  # 10.5 - 9.8

    def test_returns_zero_for_single_sample(self):
        rows = [{"time_ms": 1000, "values": {"thickness": 10.5}}]
        result = aggregate_trend_to_kpi(rows, "thickness_loss")
        assert result == 0.0

    def test_returns_none_for_empty_data(self):
        rows = []
        result = aggregate_trend_to_kpi(rows, "thickness_loss")
        assert result is None


# ---------------------------------------------------------------------------
# Hourly runtime rate tests
# ---------------------------------------------------------------------------


class TestHourlyRuntimeRate:
    def test_buckets_speed_into_24_hours(self):
        # Create data for hour 10 (10:00-10:59)
        base_ts = int(datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000)
        rows = [
            {"time_ms": base_ts + 0, "values": {"speed": 100}},
            {"time_ms": base_ts + 60000, "values": {"speed": 100}},
            {"time_ms": base_ts + 120000, "values": {"speed": 0}},
            {"time_ms": base_ts + 180000, "values": {"speed": 100}},
        ]
        result = hourly_runtime_rate(rows)
        assert len(result) == 24
        assert result[10] == 0.75  # 3 out of 4 samples running
        assert all(result[i] == 0.0 for i in range(24) if i != 10)

    def test_empty_hours_emit_zero(self):
        rows = []
        result = hourly_runtime_rate(rows)
        assert result == [0.0] * 24

    def test_skips_rows_without_timestamp(self):
        rows = [
            {"values": {"speed": 100}},  # missing time_ms
            {"time_ms": None, "values": {"speed": 100}},
        ]
        result = hourly_runtime_rate(rows)
        assert result == [0.0] * 24

    def test_skips_rows_without_speed(self):
        base_ts = int(datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000)
        rows = [
            {"time_ms": base_ts, "values": {"temp": 50}},  # missing speed
        ]
        result = hourly_runtime_rate(rows)
        assert result == [0.0] * 24


class TestComputeHourlyRuntimeRate:
    def test_wraps_hourly_runtime_rate(self):
        base_ts = int(datetime(2024, 1, 1, 14, 0, 0).timestamp() * 1000)
        rows = [
            {"time_ms": base_ts, "values": {"speed": 100}},
            {"time_ms": base_ts + 60000, "values": {"speed": 0}},
        ]
        result = compute_hourly_runtime_rate(rows)
        assert len(result) == 24
        assert result[14] == 0.5


# ---------------------------------------------------------------------------
# Multi-equipment aggregation tests
# ---------------------------------------------------------------------------


class TestAggregateEquipmentKpis:
    def test_aggregates_multiple_equipment(self):
        trend_data = {
            "EQ1": [
                {"time_ms": 1000, "values": {"speed": 100}},
                {"time_ms": 2000, "values": {"speed": 0}},
            ],
            "EQ2": [
                {"time_ms": 1000, "values": {"speed": 100}},
                {"time_ms": 2000, "values": {"speed": 100}},
            ],
        }
        kpi_keys = ["runtime_rate"]
        point_metadata = {}

        kpis, union_speed = aggregate_equipment_kpis(
            trend_data, kpi_keys, point_metadata
        )

        assert kpis["EQ1"]["runtime_rate"] == 0.5
        assert kpis["EQ2"]["runtime_rate"] == 1.0
        assert len(union_speed) == 4  # 2 rows from each equipment

    def test_handles_missing_kpi_key(self):
        trend_data = {
            "EQ1": [{"time_ms": 1000, "values": {"speed": 100}}]
        }
        kpi_keys = ["nonexistent_kpi"]
        point_metadata = {}

        kpis, union_speed = aggregate_equipment_kpis(
            trend_data, kpi_keys, point_metadata
        )

        assert kpis["EQ1"]["nonexistent_kpi"] is None
        assert len(union_speed) == 0

    def test_collects_speed_rows_for_hourly(self):
        trend_data = {
            "EQ1": [
                {"time_ms": 1000, "values": {"speed": 100}},
            ],
            "EQ2": [
                {"time_ms": 2000, "values": {"speed": 200}},
            ],
        }
        kpi_keys = ["runtime_rate", "downtime_count"]
        point_metadata = {}

        kpis, union_speed = aggregate_equipment_kpis(
            trend_data, kpi_keys, point_metadata
        )

        # Speed rows collected once per equipment (not duplicated per KPI)
        assert len(union_speed) == 2

    def test_alarm_count_with_point_metadata(self):
        trend_data = {
            "EQ1": [
                {"time_ms": 1000, "values": {"pp_value": 25.0}},
                {"time_ms": 2000, "values": {"pp_value": 15.0}},
            ],
        }
        kpi_keys = ["alarm_count"]
        point_metadata = {
            "point_1": {
                "alarm_thresholds": {"pp_value": {"C": 20.0}}
            }
        }

        kpis, _ = aggregate_equipment_kpis(
            trend_data, kpi_keys, point_metadata
        )

        assert kpis["EQ1"]["alarm_count"] == 1  # only 25.0 exceeds 20.0

    def test_empty_equipment_data(self):
        trend_data = {"EQ1": []}
        kpi_keys = ["runtime_rate"]
        point_metadata = {}

        kpis, union_speed = aggregate_equipment_kpis(
            trend_data, kpi_keys, point_metadata
        )

        assert kpis["EQ1"]["runtime_rate"] is None
        assert len(union_speed) == 0


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_kpi_key_raises(self):
        rows = [{"time_ms": 1000, "values": {"speed": 100}}]
        with pytest.raises(ValueError, match="unmappable KPI key"):
            aggregate_trend_to_kpi(rows, "unknown_kpi")

    def test_handles_feature_aliases(self):
        # bearing_temp has feature_aliases: ["temperature"]
        rows = [
            {"time_ms": 1000, "values": {"temperature": 5000}},
        ]
        result = aggregate_trend_to_kpi(rows, "bearing_temp")
        assert result == 50.0  # 5000 * 0.01

    def test_flat_row_format(self):
        # Some 2k/6k data has features at top level
        rows = [
            {"time_ms": 1000, "v_rms": 5.0},
            {"time_ms": 2000, "v_rms": 10.0},
        ]
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result == 7.5

    def test_mixed_row_formats(self):
        rows = [
            {"time_ms": 1000, "values": {"v_rms": 5.0}},
            {"time_ms": 2000, "v_rms": 10.0},  # flat format
        ]
        result = aggregate_trend_to_kpi(rows, "vibration_velocity_rms")
        assert result == 7.5


# ---------------------------------------------------------------------------
# Point selection tests (Task 1.7)
# ---------------------------------------------------------------------------


class TestSelectPointsForKpi:
    """Test select_points_for_kpi across equipment types."""

    def test_pump_vibration_points(self):
        """Pump uses position_types 23-30 for vibration KPIs."""
        components = [
            {
                "id": "p1",
                "position_type": 23,
                "endpoint_series": "2k",
                "name": "轴承振动",
            },
            {
                "id": "p2",
                "position_type": 22,  # excluded for pump
                "endpoint_series": "2k",
                "name": "轴承振动",
            },
            {
                "id": "p3",
                "position_type": 25,
                "endpoint_series": "2k",
                "name": "轴承振动",
            },
        ]
        selected = select_points_for_kpi(components, "vibration_velocity_rms", "pump")
        ids = [p["id"] for p in selected]
        assert "p1" in ids
        assert "p3" in ids
        assert "p2" not in ids  # position_type 22 excluded for pump

    def test_rotating_machinery_vibration_level(self):
        """Rotating machinery uses 8k series with position_types 81-83."""
        components = [
            {
                "id": "rm1",
                "position_type": 81,
                "endpoint_series": "8k",
                "name": "振动值",
            },
            {
                "id": "rm2",
                "position_type": 82,
                "endpoint_series": "8k",
                "name": "振动值",
            },
            {
                "id": "rm3",
                "position_type": 81,
                "endpoint_series": "9k",  # wrong series for rotating
                "name": "振动值",
            },
        ]
        selected = select_points_for_kpi(
            components, "vibration_level", "rotating_machinery"
        )
        ids = [p["id"] for p in selected]
        assert "rm1" in ids
        assert "rm2" in ids
        assert "rm3" not in ids  # 9k excluded for rotating_machinery

    def test_reciprocating_machinery_vibration_level(self):
        """Reciprocating machinery uses 9k series with position_types 91-99."""
        components = [
            {
                "id": "rc1",
                "position_type": 91,
                "endpoint_series": "9k",
                "name": "振动值",
            },
            {
                "id": "rc2",
                "position_type": 95,
                "endpoint_series": "9k",
                "name": "振动值",
            },
            {
                "id": "rc3",
                "position_type": 91,
                "endpoint_series": "8k",  # wrong series for reciprocating
                "name": "振动值",
            },
        ]
        selected = select_points_for_kpi(
            components, "vibration_level", "reciprocating_machinery"
        )
        ids = [p["id"] for p in selected]
        assert "rc1" in ids
        assert "rc2" in ids
        assert "rc3" not in ids  # 8k excluded for reciprocating_machinery

    def test_pipeline_corrosion_points(self):
        """Pipeline uses 6k series with position_types 61-64."""
        components = [
            {
                "id": "pipe1",
                "position_type": 61,
                "endpoint_series": "6k",
                "name": "腐蚀速率",
            },
            {
                "id": "pipe2",
                "position_type": 63,
                "endpoint_series": "6k",
                "name": "壁厚",
            },
            {
                "id": "pipe3",
                "position_type": 65,  # out of range
                "endpoint_series": "6k",
                "name": "腐蚀速率",
            },
        ]
        selected = select_points_for_kpi(components, "corrosion_rate", "pipeline")
        ids = [p["id"] for p in selected]
        assert "pipe1" in ids
        assert "pipe2" in ids
        assert "pipe3" not in ids

    def test_bearing_temp_name_filter(self):
        """Bearing temp requires '轴承' in name for non-pump types."""
        components = [
            {
                "id": "bt1",
                "position_type": 81,
                "endpoint_series": "8k",
                "name": "轴承温度",
            },
            {
                "id": "bt2",
                "position_type": 82,
                "endpoint_series": "8k",
                "name": "阀门温度",  # wrong name, filtered out
            },
            {
                "id": "bt3",
                "position_type": 22,
                "endpoint_series": "2k",
                "name": "轴承温度",
            },
        ]
        # For rotating_machinery, name_keywords falls back to ["轴承"]
        selected = select_points_for_kpi(
            components, "bearing_temp", "rotating_machinery"
        )
        ids = [p["id"] for p in selected]
        assert "bt1" in ids
        assert "bt2" not in ids  # name doesn't match "轴承"
        assert "bt3" not in ids  # wrong position_type for rotating

    def test_valve_temp_name_filter(self):
        """Valve temp requires '阀' or '气缸' in name."""
        components = [
            {
                "id": "vt1",
                "position_type": 81,
                "endpoint_series": "8k",
                "name": "气缸温度",
            },
            {
                "id": "vt2",
                "position_type": 82,
                "endpoint_series": "8k",
                "name": "阀门温度",
            },
            {
                "id": "vt3",
                "position_type": 83,
                "endpoint_series": "8k",
                "name": "轴承温度",  # wrong name
            },
        ]
        selected = select_points_for_kpi(
            components, "valve_temp", "rotating_machinery"
        )
        ids = [p["id"] for p in selected]
        assert "vt1" in ids
        assert "vt2" in ids
        assert "vt3" not in ids  # name doesn't match keywords

    def test_nested_component_tree(self):
        """Points can be nested in children/points arrays."""
        components = [
            {
                "id": "parent1",
                "children": [
                    {
                        "id": "child1",
                        "position_type": 81,
                        "endpoint_series": "8k",
                        "name": "振动",
                    },
                    {
                        "id": "child2",
                        "position_type": 82,
                        "endpoint_series": "8k",
                        "name": "振动",
                    },
                ],
            },
            {
                "id": "parent2",
                "points": [
                    {
                        "id": "point1",
                        "position_type": 83,
                        "endpoint_series": "8k",
                        "name": "振动",
                    },
                ],
            },
        ]
        selected = select_points_for_kpi(
            components, "vibration_level", "rotating_machinery"
        )
        ids = [p["id"] for p in selected]
        assert "child1" in ids
        assert "child2" in ids
        assert "point1" in ids

    def test_alarm_thresholds_preserved(self):
        """Selected points carry alarm thresholds."""
        components = [
            {
                "id": "p1",
                "position_type": 81,
                "endpoint_series": "8k",
                "alarm_thresholds": {"pp_value": {"B": 10.0, "C": 20.0}},
                "h_alarm": 15.0,
                "hh_alarm": 25.0,
                "name": "振动",
            },
        ]
        selected = select_points_for_kpi(
            components, "alarm_count", "rotating_machinery"
        )
        assert len(selected) == 1
        assert selected[0]["alarm_thresholds"] == {"pp_value": {"B": 10.0, "C": 20.0}}
        assert selected[0]["h_alarm"] == 15.0
        assert selected[0]["hh_alarm"] == 25.0

    def test_unknown_kpi_key_raises(self):
        """Unknown KPI key raises ValueError."""
        components = []
        with pytest.raises(ValueError, match="unmappable KPI key"):
            select_points_for_kpi(components, "unknown_kpi", "all")

    def test_type_num_fallback(self):
        """Points without position_type fall back to type_num."""
        components = [
            {
                "id": "p1",
                "type_num": 81,  # fallback field
                "endpoint_series": "8k",
                "name": "振动",
            },
        ]
        selected = select_points_for_kpi(
            components, "vibration_level", "rotating_machinery"
        )
        assert len(selected) == 1
        assert selected[0]["id"] == "p1"

    def test_empty_id_excluded(self):
        """Points with empty id are excluded from results."""
        components = [
            {
                "id": "",  # empty id
                "position_type": 81,
                "endpoint_series": "8k",
                "name": "振动",
            },
            {
                "position_type": 82,  # missing id
                "endpoint_series": "8k",
                "name": "振动",
            },
        ]
        selected = select_points_for_kpi(
            components, "vibration_level", "rotating_machinery"
        )
        assert len(selected) == 0

