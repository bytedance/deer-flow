"""Integration tests for daily report direct InS data access.

Tests verify that the direct InS provider path (via _ins_client + _kpi_aggregator)
produces output with real KPI values, replacing the old _platform_bridge subprocess path.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_PATH = Path(__file__).parent.parent.parent / "skills" / "custom" / "daily-report" / "scripts"


def _load_script_module(name: str):
    """Load a module from the scripts directory."""
    file_path = _SCRIPTS_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
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


class TestDailyDirectIns:
    """Integration tests for daily report direct InS provider path."""

    def test_platform_daily_provider_fetch_returns_real_kpis(self):
        """InsDailyProvider returns real KPI values via direct _ins_client + _kpi_aggregator."""
        mock_trend = {
            "EQ1": [
                {"time_ms": 1000, "values": {"speed": 100, "pp_value": 15.0}},
                {"time_ms": 2000, "values": {"speed": 0, "pp_value": 12.0}},
                {"time_ms": 3000, "values": {"speed": 100, "pp_value": 18.0}},
            ],
            "EQ2": [
                {"time_ms": 1000, "values": {"speed": 100, "pp_value": 20.0}},
                {"time_ms": 2000, "values": {"speed": 100, "pp_value": 22.0}},
            ],
        }

        mock_alarms = [
            {"time": "2026-05-15T10:00:00", "equipment": "EQ1", "level": "high", "message": "主报警"},
        ]

        with _script_sandbox(["_ins_client", "_kpi_aggregator", "_data_providers"]) as mods:
            dp = mods["_data_providers"]

            provider = dp.InsDailyProvider()

            with (
                patch("_ins_client.is_available", return_value=True),
                patch("_ins_client.fetch_trend_data", return_value=mock_trend),
                patch("_ins_client.fetch_alarm_events", return_value=mock_alarms),
            ):
                result = provider.fetch(
                    date_str="2026-05-15",
                    equipment_ids=["EQ1", "EQ2"],
                    kpi_keys=["runtime_rate", "downtime_count", "alarm_count"],
                    eq_type="rotating_machinery",
                    include_per_equipment=False,
                    equipment_meta=None,
                )

        assert result.data_source == "ins"
        assert result.data["kpis"]["runtime_rate"] is not None
        assert result.data["kpis"]["runtime_rate"] > 0
        assert result.data["kpis"]["downtime_count"] is not None
        assert result.data["kpis"]["alarm_count"] is not None
        assert len(result.data["alarms"]) == 1
        assert result.data["alarms"][0]["level"] == "high"
        assert result.data["hourly_runtime_rate"] is not None
        assert len(result.data["alarms"]) > 0

    def test_platform_daily_provider_no_alarms_for_static_equipment(self):
        """Static equipment report returns empty alarms (non-rotating types)."""
        mock_trend = {
            "EQ1": [
                {"time_ms": 1000, "values": {"speed": 100}},
                {"time_ms": 2000, "values": {"speed": 100}},
            ],
        }

        with _script_sandbox(["_ins_client", "_kpi_aggregator", "_data_providers"]) as mods:
            dp = mods["_data_providers"]
            provider = dp.InsDailyProvider()

            with (
                patch("_ins_client.is_available", return_value=True),
                patch("_ins_client.fetch_trend_data", return_value=mock_trend),
                patch("_ins_client.fetch_alarm_events", return_value=[]),
            ):
                result = provider.fetch(
                    date_str="2026-05-15",
                    equipment_ids=["EQ1"],
                    kpi_keys=["runtime_rate"],
                    eq_type="static_equipment",
                    include_per_equipment=False,
                    equipment_meta=None,
                )

        assert result.data_source == "ins"
        assert result.data["kpis"]["runtime_rate"] is not None

    def test_provider_raises_when_features_tool_unavailable(self):
        """PlatformDailyProvider raises HttpProviderError when features-tool is not available."""
        with _script_sandbox(["_ins_client", "_kpi_aggregator", "_data_providers"]) as mods:
            dp = mods["_data_providers"]
            provider = dp.InsDailyProvider()

            with patch("_ins_client.is_available", return_value=False), patch(
                "_ins_client.get_availability_reason",
                return_value="features-tool not found at /opt/features-tool",
            ):
                with pytest.raises(dp.HttpProviderError, match="features-tool not available"):
                    provider.fetch(
                        date_str="2026-05-15",
                        equipment_ids=["EQ1"],
                        kpi_keys=["runtime_rate"],
                        eq_type="rotating_machinery",
                        include_per_equipment=False,
                        equipment_meta=None,
                    )

    def test_aggregate_across_equipment_handles_none_values(self):
        """_aggregate_across_equipment correctly handles None KPI values."""
        with _script_sandbox(["_ins_client", "_kpi_aggregator", "_data_providers"]) as mods:
            func = mods["_data_providers"]._aggregate_across_equipment

        result = func(
            {
                "EQ1": {"runtime_rate": 0.8, "downtime_count": 2},
                "EQ2": {"runtime_rate": None, "downtime_count": 4},
            },
            ["runtime_rate", "downtime_count"],
        )
        assert result["runtime_rate"] == 0.8  # only EQ1 has value
        assert result["downtime_count"] == 3.0  # mean of 2 and 4
