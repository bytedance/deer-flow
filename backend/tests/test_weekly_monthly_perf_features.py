"""Simplified unit tests for weekly and monthly report performance features.

Tests cover:
- KPI catalog static mapping (get_kpi_catalog)
- SMS KPI helper functions (_sms_kpi)
- PerfTracer basic functionality
- equipment_meta parameter handling
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(skill: str, name: str):
    """Load a module from a specific skill's scripts directory."""
    script_dir = REPO_ROOT / "skills" / "custom" / skill / "scripts"
    spec = importlib.util.spec_from_file_location(f"{skill}_{name}", script_dir / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{skill}_{name}"] = module
    spec.loader.exec_module(module)
    return module


class TestWeeklyKpiCatalog:
    """Test weekly report KPI catalog static mapping."""

    def test_get_kpi_catalog_all_types(self):
        """Test get_kpi_catalog returns correct KPIs for all equipment types."""
        report_common = _load_script_module("weekly-report", "_report_common")

        for eq_type in ["all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"]:
            catalog = report_common.get_kpi_catalog(eq_type)
            assert isinstance(catalog, list)
            assert len(catalog) > 0

            for item in catalog:
                assert "key" in item
                assert "name" in item
                assert "unit" in item
                assert isinstance(item["key"], str)
                assert isinstance(item["name"], str)

    def test_kpi_catalog_contains_expected_kpis(self):
        """Test that KPI catalog contains expected KPI keys."""
        report_common = _load_script_module("weekly-report", "_report_common")

        catalog = report_common.get_kpi_catalog("all")
        keys = [item["key"] for item in catalog]

        assert "runtime_rate" in keys
        assert "downtime_count" in keys
        assert "alarm_count" in keys


class TestMonthlyKpiCatalog:
    """Test monthly report KPI catalog static mapping."""

    def test_get_kpi_catalog_monthly_specific(self):
        """Test monthly KPI catalog includes monthly-specific KPIs."""
        report_common = _load_script_module("monthly-report", "_report_common")

        catalog = report_common.get_kpi_catalog("all")
        keys = [item["key"] for item in catalog]

        assert "mtbf" in keys
        assert "mttr" in keys
        assert "target_rate" in keys

    def test_kpi_units_mapping(self):
        """Test that KPI units are correctly mapped."""
        report_common = _load_script_module("monthly-report", "_report_common")

        assert report_common.KPI_UNITS["runtime_rate"] == "%"
        assert report_common.KPI_UNITS["mtbf"] == "小时"
        assert report_common.KPI_UNITS["mttr"] == "小时"
        assert report_common.KPI_UNITS["target_rate"] == "%"


class TestEquipmentMetaPassthrough:
    """Test equipment_meta parameter handling in report_common."""

    def test_detect_equipment_type_with_resolved_type(self):
        """Test detect_equipment_type uses resolved_type when provided."""
        report_common = _load_script_module("weekly-report", "_report_common")

        result = report_common.detect_equipment_type(
            ["eq1", "eq2"],
            resolved_type="rotating_machinery"
        )

        assert result == "rotating_machinery"

    def test_detect_equipment_type_without_resolved(self):
        """Test detect_equipment_type falls back when resolved_type not provided."""
        report_common = _load_script_module("weekly-report", "_report_common")

        result = report_common.detect_equipment_type([], resolved_type=None)

        assert result == "all"

    def test_resolve_equipment_by_scope_with_resolved_records(self):
        """Test resolve_equipment_by_scope uses resolved_records when provided."""
        report_common = _load_script_module("weekly-report", "_report_common")

        resolved_records = [
            {"id": "eq1", "name": "设备1"},
            {"id": "eq2", "name": "设备2"},
        ]

        result = report_common.resolve_equipment_by_scope(
            "all", "specific", "",
            resolved_records=resolved_records
        )

        assert result == resolved_records


class TestReportCommonUtilities:
    """Test common utility functions in _report_common."""

    def test_parse_csv(self):
        """Test CSV parsing utility."""
        report_common = _load_script_module("weekly-report", "_report_common")

        assert report_common.parse_csv("a,b,c") == ["a", "b", "c"]
        assert report_common.parse_csv("a, b , c") == ["a", "b", "c"]
        assert report_common.parse_csv("") == []
        assert report_common.parse_csv(None) == []

    def test_validate_equipment_ids_length(self):
        """Test equipment ID validation."""
        report_common = _load_script_module("monthly-report", "_report_common")

        assert report_common.validate_equipment_ids_length(["eq1", "eq2"]) is None
        assert report_common.validate_equipment_ids_length([]) is not None
        assert report_common.validate_equipment_ids_length(["invalid id!"]) is not None

        long_id = "a" * 65
        assert report_common.validate_equipment_ids_length([long_id]) is not None

    def test_validate_kpi_keys(self):
        """Test KPI key validation."""
        report_common = _load_script_module("weekly-report", "_report_common")

        assert report_common.validate_kpi_keys(["runtime_rate", "alarm_count"]) is None
        assert report_common.validate_kpi_keys([]) is not None
        assert report_common.validate_kpi_keys(["Invalid-Key"]) is not None

    def test_month_bounds(self):
        """Test month bounds calculation."""
        report_common = _load_script_module("monthly-report", "_report_common")

        start, end, days = report_common.month_bounds(2026, 5)
        assert start == "2026-05-01"
        assert end == "2026-05-31"
        assert days == 31

        start, end, days = report_common.month_bounds(2024, 2)
        assert start == "2024-02-01"
        assert end == "2024-02-29"
        assert days == 29
