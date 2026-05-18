"""End-to-end smoke harness for Story M5 (no GenUI/runtime layer).

Walks every edge case the sprint plan M5 acceptance list demands:
- compare_with single basis / dual basis / none
- compare=previous_year_month missing data (2024-02 → 2023-02 below horizon)
- zero-failure month (synthetic maintenance override)
- leap-year (2024-02), regular Feb (2025-02), 31-day month (2026-12)
- cross-year same-month (2026-01 → 2025-01)
- critical_events empty / non-empty rendering
- improvement_tracking empty / non-empty rendering
- demo banner appears when data_source == demo_fallback

Run from repo root:
    MONTHLY_REPORT_OUTPUT_DIR=/tmp/m-e2e python skills/custom/data-analyst/scripts/_smoke_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

import query_monthly as qm  # noqa: E402
import monthly_kpi as mk  # noqa: E402
import export_report as er  # noqa: E402


def _run_case(label: str, args: dict, mutate_payload=None) -> dict:
    """Run query_monthly → monthly_kpi → render_monthly_markdown end-to-end."""
    print(f"\n=== {label} ===")
    query_kpis = [k for k in args["kpis"] if k not in qm.SPECIAL_KPIS]
    payload = qm.build_result(
        report_month=args["report_month"],
        equipment_ids=args["equipment_ids"],
        kpi_keys=query_kpis,
        compare_bases=args["compare_bases"],
        eq_type=args.get("eq_type", "all"),
        aggregate=args.get("aggregate", False),
        is_scope_mode=False,
    )
    payload["kpi_keys"] = args["kpis"]
    if mutate_payload:
        mutate_payload(payload)

    kpi_out = mk.compute(payload)
    md = er.render_monthly_markdown(kpi_out)

    return {
        "payload": payload,
        "kpi_out": kpi_out,
        "md": md,
    }


def main() -> int:
    failures: list[str] = []

    # 1. Dual baseline + non-zero failures (April 2026)
    r = _run_case(
        "M5-1 dual baseline (2026-04)",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001", "RM-002"],
            "kpis": ["runtime_rate", "downtime_count", "alarm_count", "mtbf", "mttr", "target_rate"],
            "compare_bases": ["previous_month", "previous_year_month"],
        },
    )
    mtbf = next(k for k in r["kpi_out"]["kpi_summary"] if k["key"] == "mtbf")
    assert mtbf["current_mean"] is not None, "mtbf should be derived for non-zero failures"
    assert mtbf["previous_month_mean"] is not None, "previous_month_mean must be present"
    assert mtbf["previous_year_month_mean"] is not None, "previous_year_month_mean (with month) required"
    assert "previous_year_mean" not in mtbf, "old field name 'previous_year_mean' must NOT appear (sprint plan M2)"
    print("  [OK] MTBF dual baseline + correct field naming")

    # 2. Cross-year same month (2026-01 → previous_month=2025-12, prev_year=2025-01)
    r = _run_case(
        "M5-2 cross-year (2026-01)",
        {
            "report_month": "2026-01",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate", "mtbf", "mttr"],
            "compare_bases": ["previous_month", "previous_year_month"],
        },
    )
    cp = r["payload"]["compare_periods"]
    assert cp["previous_month"]["start"] == "2025-12-01", "previous_month must roll year back: 2026-01 → 2025-12"
    assert cp["previous_year_month"]["start"] == "2025-01-01", "previous_year_month: 2026-01 → 2025-01"
    print(f"  [OK] Cross-year periods: prev_month={cp['previous_month']}, prev_yr={cp['previous_year_month']}")

    # 3. Leap-year Feb (2024-02): 29 days, buckets=[7,7,7,7,1]; YoY=2023-02 below horizon → null
    r = _run_case(
        "M5-3 leap-year Feb (2024-02), YoY missing",
        {
            "report_month": "2024-02",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate", "mtbf"],
            "compare_bases": ["previous_year_month"],
        },
    )
    assert r["payload"]["report_period"]["day_count"] == 29, "Leap Feb must be 29 days"
    bucket_days = [b["day_count"] for b in r["payload"]["report_period"]["week_buckets"]]
    assert bucket_days == [7, 7, 7, 7, 1], f"Leap Feb buckets [7,7,7,7,1]; got {bucket_days}"
    assert r["payload"]["compare"]["previous_year_month"] is None, "YoY for 2024-02 (→2023-02) must be null (below horizon)"
    assert r["payload"]["compare_warning"] is not None, "compare_warning must surface YoY missing"
    print(f"  [OK] 2024-02 day_count=29, buckets={bucket_days}, YoY=null + warning")

    # 4. Regular Feb (2025-02): 28 days, buckets=[7,7,7,7]
    r = _run_case(
        "M5-4 regular Feb (2025-02)",
        {
            "report_month": "2025-02",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate"],
            "compare_bases": ["previous_month"],
        },
    )
    bucket_days = [b["day_count"] for b in r["payload"]["report_period"]["week_buckets"]]
    assert r["payload"]["report_period"]["day_count"] == 28
    assert bucket_days == [7, 7, 7, 7], f"Regular Feb buckets [7,7,7,7]; got {bucket_days}"
    print(f"  [OK] 2025-02 day_count=28, buckets={bucket_days}")

    # 5. 31-day month (2026-12): buckets=[7,7,7,7,3]
    r = _run_case(
        "M5-5 31-day month (2026-12)",
        {
            "report_month": "2026-12",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate", "alarm_count"],
            "compare_bases": ["previous_month"],
        },
    )
    bucket_days = [b["day_count"] for b in r["payload"]["report_period"]["week_buckets"]]
    assert r["payload"]["report_period"]["day_count"] == 31
    assert bucket_days == [7, 7, 7, 7, 3], f"31-day buckets [7,7,7,7,3]; got {bucket_days}"
    print(f"  [OK] 2026-12 day_count=31, buckets={bucket_days}")

    # 6. Zero-failure month (mutate maintenance to total_failures=0)
    def _zero_failure(payload):
        payload["current"]["maintenance"] = {
            "total_failures": 0,
            "total_uptime_hours": 24 * payload["report_period"]["day_count"],
            "total_downtime_minutes": 0,
            "total_repair_minutes": 0,
            "mtbf_hours": None,
            "mttr_hours": None,
        }
        payload["current"]["alarms"] = []
        payload["current"]["critical_events"] = []
        payload["current"]["improvement_tracking"] = []

    r = _run_case(
        "M5-6 zero-failure month + empty critical/improvement",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate", "mtbf", "mttr"],
            "compare_bases": ["previous_month"],
        },
        mutate_payload=_zero_failure,
    )
    mtbf = next(k for k in r["kpi_out"]["kpi_summary"] if k["key"] == "mtbf")
    mttr = next(k for k in r["kpi_out"]["kpi_summary"] if k["key"] == "mttr")
    assert mtbf["current_mean"] is None, "Zero-failure month: mtbf.current_mean must be None"
    assert mttr["current_mean"] is None, "Zero-failure month: mttr.current_mean must be None"
    assert "零故障" in r["kpi_out"]["monthly_review"], "monthly_review must mention 零故障"
    # Empty arrays must NOT render the conditional tables
    assert "5. 重大事件回顾" not in r["md"], "critical_events empty → section 5 must be skipped"
    assert "7. 改进措施跟踪" not in r["md"], "improvement_tracking empty → section 7 must be skipped"
    print("  [OK] Zero failure: MTBF/MTTR=null, 零故障 phrase present, conditional sections skipped")

    # 7. compare_with=none → no MoM/YoY columns populated, kpi_summary still emitted
    r = _run_case(
        "M5-7 none compare basis",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate"],
            "compare_bases": [],  # empty effective bases (none case)
        },
    )
    rt = next(k for k in r["kpi_out"]["kpi_summary"] if k["key"] == "runtime_rate")
    assert rt["delta_mom_pct"] is None
    assert rt["delta_yoy_pct"] is None
    assert "6. 月环比 + 同比" not in r["md"], "section 6 must be skipped when compare_types empty"
    print("  [OK] none compare: delta_mom_pct/delta_yoy_pct=None, section 6 skipped")

    # 8. STALE summary_markdown injection (regression for Fix #7)
    r = _run_case(
        "M5-8 summary_markdown STALE injection",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate"],
            "compare_bases": ["previous_month"],
        },
    )
    r["kpi_out"]["summary_markdown"] = "STALE-MUST-NOT-APPEAR"
    md_after_inject = er.render_monthly_markdown(r["kpi_out"])
    assert "STALE-MUST-NOT-APPEAR" not in md_after_inject, "render_monthly_markdown must ignore summary_markdown"
    print("  [OK] summary_markdown ignored by render_monthly_markdown")

    # 9. Demo banner appears for demo_fallback data
    r = _run_case(
        "M5-9 demo banner",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate"],
            "compare_bases": ["previous_month"],
        },
    )
    assert "演示数据" in r["md"], "demo banner must appear in markdown when data_source=demo_fallback"
    print("  [OK] demo banner present")

    # 10. monthly_kpi.py never emits summary_markdown
    r = _run_case(
        "M5-10 summary_markdown absent from kpi output",
        {
            "report_month": "2026-04",
            "equipment_ids": ["RM-001"],
            "kpis": ["runtime_rate", "mtbf"],
            "compare_bases": ["previous_month"],
        },
    )
    assert "summary_markdown" not in r["kpi_out"], "monthly_kpi.py must not output summary_markdown (sprint plan M2)"
    print("  [OK] kpi_out has no summary_markdown key")

    # 11. write_report end-to-end (file actually written)
    tmp = Path(os.environ.get("MONTHLY_REPORT_OUTPUT_DIR", "/tmp/m-e2e"))
    tmp.mkdir(parents=True, exist_ok=True)
    out_md = er.write_report(r["kpi_out"], "md", report_type="monthly")
    assert out_md.exists(), "monthly_report.md must be written"
    assert out_md.name == "monthly_report.md", f"expected monthly_report.md, got {out_md.name}"
    print(f"  [OK] write_report(report_type='monthly') wrote {out_md}")

    # 12. write_report default report_type=daily still works (no regression)
    daily_payload = {
        "report_date": "2026-04-01",
        "compare_type": "none",
        "overall_status": {"level": "good", "summary": "ok"},
        "kpi_summary": [],
        "trend_chart": {},
        "alarm_table": [],
        "recommendations": [],
    }
    try:
        out_daily = er.write_report(daily_payload, "md")  # no report_type
        assert out_daily.name == "daily_report.md", f"daily fallback regression: got {out_daily.name}"
        print(f"  [OK] daily fallback (report_type defaulted) → {out_daily.name}")
    except Exception as exc:
        failures.append(f"daily fallback regression broken: {exc}")
        print(f"  [FAIL] daily fallback regression: {exc}")

    print("\n=== SUMMARY ===")
    if failures:
        print("FAILED CASES:")
        for f in failures:
            print(f" - {f}")
        return 1
    print("ALL CASES PASSED [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
