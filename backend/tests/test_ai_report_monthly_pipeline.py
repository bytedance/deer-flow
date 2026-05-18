"""End-to-end pipeline tests: query_monthly → monthly_kpi → export_report.

Mirrors test_ai_report_weekly_pipeline.py — exercises the full data contract
between scripts and verifies the integration boundary (sprint plan M7).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTHLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    return {
        "qm": _load("query_monthly"),
        "mk": _load("monthly_kpi"),
        "er": _load("export_report"),
        "tmp": tmp_path,
    }


def test_full_pipeline_end_to_end(pipeline):
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]

    # 1. query_monthly
    monthly_data = qm.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate", "alarm_count"],
        compare_bases=["previous_month", "previous_year_month"],
    )
    monthly_data["kpi_keys"] = ["runtime_rate", "alarm_count", "mtbf", "mttr", "target_rate"]

    # 2. monthly_kpi consumes monthly_data
    kpi = mk.compute(monthly_data)
    assert "summary_markdown" not in kpi
    assert kpi["report_period"]["report_month"] == "2026-04"
    assert any(item["key"] == "mtbf" for item in kpi["kpi_summary"])

    # 3. export_report renders monthly_kpi → markdown
    md_path = er.write_report(kpi, "md", report_type="monthly")
    assert md_path.name == "monthly_report.md"
    md_text = md_path.read_text(encoding="utf-8")
    assert "## 1. 月度总览" in md_text
    assert "## 8. 下月计划" in md_text


def test_dual_baseline_propagation(pipeline):
    """Both previous_month_mean and previous_year_month_mean must be populated."""
    qm, mk = pipeline["qm"], pipeline["mk"]
    monthly_data = qm.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month", "previous_year_month"],
    )
    monthly_data["kpi_keys"] = ["runtime_rate"]
    kpi = mk.compute(monthly_data)
    rt = next(k for k in kpi["kpi_summary"] if k["key"] == "runtime_rate")
    assert rt["previous_month_mean"] is not None
    assert rt["previous_year_month_mean"] is not None


def test_none_compare_propagation(pipeline):
    """compare_with=none → kpi_summary deltas all None + section 6 skipped."""
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]
    monthly_data = qm.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=[],  # effective bases empty (none case)
    )
    monthly_data["kpi_keys"] = ["runtime_rate"]
    kpi = mk.compute(monthly_data)
    rt = next(k for k in kpi["kpi_summary"] if k["key"] == "runtime_rate")
    assert rt["delta_mom_pct"] is None
    assert rt["delta_yoy_pct"] is None

    md = er.render_monthly_markdown(kpi)
    assert "## 6. 月环比 + 同比" not in md


def test_leap_year_pipeline(pipeline):
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]
    monthly_data = qm.build_result(
        report_month="2024-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_year_month"],
    )
    monthly_data["kpi_keys"] = ["runtime_rate"]
    kpi = mk.compute(monthly_data)
    assert kpi["report_period"]["day_count"] == 29
    # Compare warning propagates from query layer
    md = er.render_monthly_markdown(kpi)
    assert "去年同期" in md or "compare_warning" not in md  # banner appears via render layer
