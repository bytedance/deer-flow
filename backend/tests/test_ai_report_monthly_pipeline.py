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
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "monthly-report" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


from unittest.mock import MagicMock


def _fake_fetch_month(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
    """Stub fetch_month_with_provenance returning synthetic InS-tagged monthly data."""
    kpis_mean = {}
    for k in kpi_keys:
        kpis_mean[k] = {
            "runtime_rate": 0.93, "alarm_count": 4.6, "mtbf": 115.3, "mttr": 0.89, "target_rate": 0.80,
        }.get(k, 1.0)

    weekly = [
        {
            "label": f"W{i+1}",
            "day_count": 7,
            "kpis_mean": dict(kpis_mean),
            "kpis_max": dict(kpis_mean),
            "kpis_min": dict(kpis_mean),
            "kpis_std": {k: 0.01 for k in kpis_mean},
        }
        for i in range(4)
    ]

    current = {
        "weekly": weekly,
        "aggregated": {
            "kpis_mean": dict(kpis_mean),
            "kpis_max": dict(kpis_mean),
            "kpis_min": dict(kpis_mean),
            "kpis_std": {k: 0.01 for k in kpis_mean},
            "kpis_target_rate": {k: 0.80 for k in kpis_mean},
        },
        "maintenance": {
            "total_failures": 6,
            "total_uptime_hours": 692,
            "total_downtime_minutes": 480,
            "total_repair_minutes": 320,
            "mtbf_hours": 115.3,
            "mttr_hours": 0.89,
        },
        "alarms": [],
        "critical_events": [],
        "improvement_tracking": [
            {"id": "IMP-1", "owner": "x", "plan": "p1", "due_date": f"{report_month}-15", "status": "done", "note": ""},
        ],
        "kpi_units": {k: "%" if "rate" in k else "条" if "alarm" in k else "h" for k in kpis_mean},
    }
    return (current, "ins", [])


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


def test_full_pipeline_end_to_end(pipeline, monkeypatch):
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]

    monkeypatch.setattr(qm, "fetch_month_with_provenance", _fake_fetch_month)

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


def test_dual_baseline_propagation(pipeline, monkeypatch):
    """Both previous_month_mean and previous_year_month_mean must be populated."""
    qm, mk = pipeline["qm"], pipeline["mk"]

    monkeypatch.setattr(qm, "fetch_month_with_provenance", _fake_fetch_month)

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


def test_none_compare_propagation(pipeline, monkeypatch):
    """compare_with=none → kpi_summary deltas all None + section 6 skipped."""
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]

    monkeypatch.setattr(qm, "fetch_month_with_provenance", _fake_fetch_month)

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


def test_leap_year_pipeline(pipeline, monkeypatch):
    qm, mk, er = pipeline["qm"], pipeline["mk"], pipeline["er"]

    monkeypatch.setattr(qm, "fetch_month_with_provenance", _fake_fetch_month)

    monthly_data = qm.build_result(
        report_month="2024-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_year_month"],
    )
    monthly_data["kpi_keys"] = ["runtime_rate"]
    kpi = mk.compute(monthly_data)
    assert kpi["report_period"]["day_count"] == 29
    md = er.render_monthly_markdown(kpi)
    assert "去年同期" in md or "compare_warning" not in md


# ---------------------------------------------------------------------------
# Unit tests for fetch_month_with_provenance batch-fetch path
# ---------------------------------------------------------------------------


def _build_fake_daily_entry(date_str: str, kpi_keys: list[str]) -> dict:
    """Return a single daily entry matching the InS batch contract."""
    kpis = {}
    for k in kpi_keys:
        kpis[k] = {
            "runtime_rate": 0.93,
            "alarm_count": 2.0,
            "mtbf": 115.3,
            "mttr": 0.89,
            "target_rate": 0.80,
        }.get(k, 1.0)
    return {
        "date": date_str,
        "kpis": kpis,
        "kpi_units": {k: "%" if "rate" in k else "条" for k in kpi_keys},
        "alarms": [],
    }


def test_fetch_month_batch_30_day(pipeline, monkeypatch):
    """fetch_month_with_provenance calls the monthly provider with correct params."""
    qm = pipeline["qm"]

    fake_daily = [
        _build_fake_daily_entry("2026-04-%02d" % d, ["runtime_rate"]) for d in range(1, 31)
    ]
    fake_provider = MagicMock()
    fake_provider.fetch.return_value = qm.load_sibling_module("_data_providers").ProviderResult(
        data={"daily_entries": fake_daily}, data_source="ins"
    )
    monkeypatch.setattr(
        qm.load_sibling_module("_data_providers"), "get_provider", lambda source, mode=None: fake_provider
    )

    current, source, notes = qm.fetch_month_with_provenance(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
    )

    fake_provider.fetch.assert_called_once()
    call_kwargs = fake_provider.fetch.call_args.kwargs
    assert call_kwargs["report_month"] == "2026-04"
    assert call_kwargs["equipment_ids"] == ["RM-001"]
    assert call_kwargs["kpi_keys"] == ["runtime_rate"]
    assert source == "ins"
    assert notes == []
    assert current["aggregated"]["kpis_mean"]["runtime_rate"] == pytest.approx(0.93)


def test_fetch_month_batch_leap_year_february(pipeline, monkeypatch):
    """fetch_month_with_provenance handles February in leap years (day_count=29)."""
    qm = pipeline["qm"]

    fake_daily = [
        _build_fake_daily_entry("2024-02-%02d" % d, ["runtime_rate"]) for d in range(1, 30)
    ]
    fake_provider = MagicMock()
    fake_provider.fetch.return_value = qm.load_sibling_module("_data_providers").ProviderResult(
        data={"daily_entries": fake_daily}, data_source="ins"
    )
    monkeypatch.setattr(
        qm.load_sibling_module("_data_providers"), "get_provider", lambda source, mode=None: fake_provider
    )

    current, source, notes = qm.fetch_month_with_provenance(
        report_month="2024-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
    )

    fake_provider.fetch.assert_called_once()
    call_kwargs = fake_provider.fetch.call_args.kwargs
    assert call_kwargs["report_month"] == "2024-02"
