"""Demo helpers extracted from query_monthly.py to keep the main script under
the 800-line cap. These produce stable, deterministic placeholder data used
when running without a real KPI catalog / maintenance feed.

Contracts preserved verbatim from the original query_monthly.py:
- ``_demo_targets`` returns the fixed 4-key target map.
- ``_deterministic_int`` mirrors the query_daily helper.
- ``_demo_maintenance`` keeps the zero-failure edge case and emits
  ``total_uptime_hours = day_count * 24 - downtime_minutes / 60``.
- ``_demo_improvement_tracking`` always returns 3 entries spanning
  ``done`` / ``in_progress`` / ``delayed`` (sprint plan M1 contract).
"""

from __future__ import annotations


def _demo_targets() -> dict[str, dict]:
    """Stable demo target ranges used when running without a real KPI catalog."""
    return {
        "runtime_rate": {"min": 0.85},
        "vibration_level": {"max": 4.0},
        "outlet_pressure": {"min": 0.7, "max": 1.5},
        "bearing_temp": {"max": 75.0},
    }


def _deterministic_int(seed: str, low: int, high: int) -> int:
    """Stable demo int derived from a seed string (mirror query_daily helper)."""
    digest = abs(hash(seed))
    span = high - low + 1
    if span <= 0:
        return low
    return low + (digest % span)


def _demo_maintenance(report_month: str, day_count: int, equipment_ids: list[str]) -> dict:
    seed_base = f"maint|{report_month}|{','.join(sorted(equipment_ids))}"
    failures = _deterministic_int(seed_base + "|f", 0, max(1, len(equipment_ids))) + (day_count // 10)
    if failures == 0:
        downtime_minutes = 0
        repair_minutes = 0
    else:
        downtime_minutes = failures * _deterministic_int(seed_base + "|d", 30, 120)
        repair_minutes = failures * _deterministic_int(seed_base + "|r", 20, 90)
    total_uptime_hours = round(day_count * 24 - downtime_minutes / 60.0, 2)
    mtbf_hours: float | None = round(total_uptime_hours / failures, 2) if failures > 0 else None
    mttr_hours: float | None = round(repair_minutes / failures / 60.0, 2) if failures > 0 else None
    return {
        "total_failures": failures,
        "total_uptime_hours": total_uptime_hours,
        "total_downtime_minutes": downtime_minutes,
        "total_repair_minutes": repair_minutes,
        "mtbf_hours": mtbf_hours,
        "mttr_hours": mttr_hours,
    }


def _demo_improvement_tracking(report_month: str, equipment_ids: list[str]) -> list[dict]:
    """Demo data MUST cover done / in_progress / delayed states (sprint plan M1)."""
    primary = equipment_ids[0] if equipment_ids else "RM-001"
    secondary = equipment_ids[1] if len(equipment_ids) > 1 else "P-101"
    year, month = report_month.split("-")
    py, pm = (int(year), int(month) - 1) if month != "01" else (int(year) - 1, 12)
    prev_tag = f"{py:04d}-{pm:02d}"
    return [
        {
            "id": f"IMP-{prev_tag}-01",
            "owner": "张三",
            "plan": f"{primary} 轴承温度联合诊断",
            "due_date": f"{year}-{month}-15",
            "status": "done",
            "note": "已完成，温度告警下降 60%",
        },
        {
            "id": f"IMP-{prev_tag}-02",
            "owner": "李四",
            "plan": f"{primary} 振动传感器更换",
            "due_date": f"{year}-{month}-28",
            "status": "in_progress",
            "note": "备件到货延期，预计下月初完成",
        },
        {
            "id": f"IMP-{py - (1 if pm == 1 else 0):04d}-{((pm - 1) or 12):02d}-07",
            "owner": "王五",
            "plan": f"{secondary} 冷却水泵密封件更换",
            "due_date": f"{year}-{month}-10",
            "status": "delayed",
            "note": "因供应商交期延误，重新调度至下月上旬",
        },
    ]
