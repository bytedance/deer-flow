"""Integration tests for report scripts with USE_PLATFORM=true (Tasks 6.6-6.7).

Tests verify that the platform bridge path produces output with real KPI values
(not all None/0) when USE_PLATFORM=true is set.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_PATH = Path(__file__).parent.parent.parent / "skills" / "custom" / "data-analyst" / "scripts"


def _load_script_module(name: str):
    """Load a module from the scripts directory."""
    file_path = _SCRIPTS_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _script_sandbox(module_names: list[str]):
    """Load script modules and register them in sys.modules for cross-imports.

    Cleans up sys.modules entries on exit to avoid leaking into other tests.
    """
    saved = {}
    for name in module_names:
        saved[name] = sys.modules.get(name)
    try:
        modules = {}
        for name in module_names:
            mod = _load_script_module(name)
            sys.modules[name] = mod
            modules[name] = mod
        yield modules
    finally:
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig


class TestDailyPlatformBridge:
    """Integration tests for query_daily.py platform bridge path."""

    def test_fetch_day_via_platform_returns_real_kpis(self):
        """Platform bridge returns real KPI values, not placeholders."""
        mock_trend_result = {
            "ok": True,
            "data": {
                "equipment_data": {
                    "EQ1": [
                        {"time_ms": 1000, "values": {"speed": 100, "pp_value": 15.0}},
                        {"time_ms": 2000, "values": {"speed": 0, "pp_value": 12.0}},
                        {"time_ms": 3000, "values": {"speed": 100, "pp_value": 18.0}},
                    ],
                    "EQ2": [
                        {"time_ms": 1000, "values": {"speed": 100, "pp_value": 20.0}},
                        {"time_ms": 2000, "values": {"speed": 100, "pp_value": 22.0}},
                    ],
                },
                "equipment_ids": ["EQ1", "EQ2"],
                "point_metadata": {},
            },
            "source_system_keys": ["ins_prod"],
        }

        mock_kpi_result = {
            "ok": True,
            "data": {
                "kpis": {
                    "EQ1": {"runtime_rate": 0.6667, "downtime_count": 1, "alarm_count": 0},
                    "EQ2": {"runtime_rate": 1.0, "downtime_count": 0, "alarm_count": 0},
                },
                "hourly_runtime_rate": [0.0] * 24,
            },
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        }

        mock_alarm_result = {
            "ok": True,
            "data": {"equipment_data": {"EQ1": [], "EQ2": []}},
            "source_system_keys": ["ins_prod"],
        }

        with patch.dict(os.environ, {"USE_PLATFORM": "true"}):
            with _script_sandbox(["_platform_bridge", "query_daily"]) as mods:
                bridge = mods["_platform_bridge"]
                daily = mods["query_daily"]

                with (
                    patch.object(bridge, "call_capability", side_effect=[mock_trend_result, mock_alarm_result]),
                    patch.object(bridge, "call_action", return_value=mock_kpi_result),
                ):
                    data, source, notes = daily._fetch_day_via_platform(
                        date_str="2026-05-15",
                        equipment_ids=["EQ1", "EQ2"],
                        kpi_keys=["runtime_rate", "downtime_count", "alarm_count"],
                        eq_type="rotating_machinery",
                        include_per_equipment=False,
                        equipment_meta=None,
                    )

        assert data["kpis"]["runtime_rate"] is not None
        assert data["kpis"]["runtime_rate"] > 0
        assert data["kpis"]["downtime_count"] is not None
        assert data["kpis"]["alarm_count"] is not None
        assert source == "ins_prod"

    def test_build_result_with_compare_uses_platform(self):
        """build_result calls platform bridge for both current and compare."""
        mock_trend_result = {
            "ok": True,
            "data": {
                "equipment_data": {"EQ1": [{"time_ms": 1000, "values": {"speed": 100}}]},
                "equipment_ids": ["EQ1"],
                "point_metadata": {},
            },
            "source_system_keys": ["ins_prod"],
        }

        mock_kpi_result = {
            "ok": True,
            "data": {
                "kpis": {"EQ1": {"runtime_rate": 0.75}},
                "hourly_runtime_rate": [0.0] * 24,
            },
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        }

        mock_alarm_result = {
            "ok": True,
            "data": {"equipment_data": {"EQ1": []}},
            "source_system_keys": ["ins_prod"],
        }

        with patch.dict(os.environ, {"USE_PLATFORM": "true"}):
            with _script_sandbox(["_platform_bridge", "query_daily"]) as mods:
                bridge = mods["_platform_bridge"]
                daily = mods["query_daily"]

                with (
                    patch.object(bridge, "call_capability", side_effect=[
                        mock_trend_result, mock_alarm_result,
                        mock_trend_result, mock_alarm_result,
                    ]),
                    patch.object(bridge, "call_action", return_value=mock_kpi_result),
                ):
                    result = daily.build_result(
                        date_str="2026-05-15",
                        equipment_ids=["EQ1"],
                        kpi_keys=["runtime_rate"],
                        compare="previous_day",
                        eq_type="rotating_machinery",
                    )

        assert result["current"]["kpis"]["runtime_rate"] is not None
        assert result["compare"]["kpis"]["runtime_rate"] is not None
        assert result["compare_date"] == "2026-05-14"


class TestWeeklyPlatformBridge:
    """Integration tests for query_weekly.py platform bridge path."""

    def test_fetch_week_via_platform_returns_real_kpis(self):
        """Platform bridge returns real KPI values for weekly aggregation."""
        mock_trend_result = {
            "ok": True,
            "data": {
                "equipment_data": {"EQ1": [{"time_ms": 1000, "values": {"speed": 100}}]},
                "equipment_ids": ["EQ1"],
                "point_metadata": {},
            },
            "source_system_keys": ["ins_prod"],
        }

        mock_kpi_result = {
            "ok": True,
            "data": {
                "kpis": {"EQ1": {"runtime_rate": 0.8}},
                "hourly_runtime_rate": [0.0] * 24,
            },
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        }

        mock_alarm_result = {
            "ok": True,
            "data": {"equipment_data": {"EQ1": []}},
            "source_system_keys": ["ins_prod"],
        }

        with patch.dict(os.environ, {"USE_PLATFORM": "true"}):
            with _script_sandbox(["_platform_bridge", "_report_common", "query_daily", "query_weekly"]) as mods:
                bridge = mods["_platform_bridge"]
                weekly = mods["query_weekly"]

                with (
                    patch.object(bridge, "call_capability", side_effect=[
                        mock_trend_result, mock_alarm_result,
                    ] * 7),
                    patch.object(bridge, "call_action", return_value=mock_kpi_result),
                ):
                    data, source, notes = weekly._fetch_week_via_platform(
                        week_start="2026-05-11",
                        equipment_ids=["EQ1"],
                        kpi_keys=["runtime_rate"],
                        eq_type="rotating_machinery",
                        aggregate=False,
                        equipment_meta=None,
                    )

        assert len(data["daily"]) == 7
        for entry in data["daily"]:
            assert entry["kpis"]["runtime_rate"] is not None
            assert entry["kpis"]["runtime_rate"] > 0

        assert data["aggregated"]["kpis_mean"]["runtime_rate"] is not None
        assert data["aggregated"]["kpis_mean"]["runtime_rate"] > 0


class TestMonthlyPlatformBridge:
    """Integration tests for query_monthly.py platform bridge path."""

    def test_fetch_month_via_platform_returns_real_kpis(self):
        """Platform bridge returns real KPI values for monthly aggregation."""
        mock_trend_result = {
            "ok": True,
            "data": {
                "equipment_data": {"EQ1": [{"time_ms": 1000, "values": {"speed": 100}}]},
                "equipment_ids": ["EQ1"],
                "point_metadata": {},
            },
            "source_system_keys": ["ins_prod"],
        }

        mock_kpi_result = {
            "ok": True,
            "data": {
                "kpis": {"EQ1": {"runtime_rate": 0.85, "alarm_count": 2}},
                "hourly_runtime_rate": [0.0] * 24,
            },
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        }

        mock_alarm_result = {
            "ok": True,
            "data": {"equipment_data": {"EQ1": []}},
            "source_system_keys": ["ins_prod"],
        }

        with patch.dict(os.environ, {"USE_PLATFORM": "true"}):
            with _script_sandbox(["_platform_bridge", "_report_common", "query_daily", "query_monthly"]) as mods:
                bridge = mods["_platform_bridge"]
                monthly = mods["query_monthly"]

                with (
                    patch.object(bridge, "call_capability", side_effect=[
                        mock_trend_result, mock_alarm_result,
                    ] * 31),
                    patch.object(bridge, "call_action", return_value=mock_kpi_result),
                ):
                    data, source, notes = monthly._fetch_month_via_platform(
                        report_month="2026-05",
                        equipment_ids=["EQ1"],
                        kpi_keys=["runtime_rate", "alarm_count"],
                        eq_type="rotating_machinery",
                        aggregate=False,
                        equipment_meta=None,
                    )

        assert len(data["weekly"]) > 0
        for bucket in data["weekly"]:
            assert bucket["kpis_mean"]["runtime_rate"] is not None
            assert bucket["kpis_mean"]["runtime_rate"] > 0

        assert data["aggregated"]["kpis_mean"]["runtime_rate"] is not None
        assert data["aggregated"]["kpis_mean"]["runtime_rate"] > 0
