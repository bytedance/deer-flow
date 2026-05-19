"""Fault-context demo data for diagnosis reports.

Sprint S2 enhancement — replaces the 69-line stub with a richer deterministic
demo that the downstream ``build_fault_timeline`` and ``diagnosis_analysis``
scripts can chew on to produce a §13.2-compliant report.

Output contract (``fault_context.json``):
- ``fault_time`` / ``equipment_id`` / ``symptom`` / ``include_related``
- ``operations[]`` — pre-event 24h time-series samples (multiple metrics),
  each with ``id`` so evidence trails can reference a specific point.
- ``alarms[]`` — pre/post 6h alarm flow with ``id`` / ``time`` / ``level`` /
  ``equipment`` / ``message``.
- ``work_orders[]`` — recent 3 work orders with id / title / status / owner /
  created_at.
- ``maintenance_records[]`` — last 30 days maintenance entries.
- ``related_equipment[]`` — only populated when ``--include-related-equipment``.
- ``data_source: demo_fallback``.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    write_json,
)

import _data_provider_impls  # noqa: F401 — register-only
from _data_providers import fetch_with_fallback


SCHEMA_VERSION = "1"


def _seed_int(seed: str, low: int, high: int) -> int:
    """Deterministic pseudo-int derived from seed (mirrors query_daily helper)."""
    digest = abs(hash(seed))
    span = high - low + 1
    if span <= 0:
        return low
    return low + (digest % span)


def _seed_float(seed: str, low: float, high: float) -> float:
    digest = abs(hash(seed))
    span = high - low
    return round(low + (digest % 1000) / 1000.0 * span, 4)


def _operations(fault_day: date, equipment_id: str) -> list[dict]:
    """Pre-event 24h hourly samples across 3 metrics.

    Each point carries an ``id`` so diagnosis_analysis evidence can point at a
    specific sample. Values escalate towards fault_time to give a deterministic
    upward drift the analyzer can detect.
    """
    base_dt = datetime.combine(fault_day, time.min)
    operations: list[dict] = []
    # Pre-event 24 hours (00:00 → fault hour 8) — drift the vibration & temp up
    for hour in range(24):
        ts = base_dt + timedelta(hours=hour)
        progress = hour / 23.0
        operations.append(
            {
                "id": f"OP-{ts.strftime('%H%M')}-vibration",
                "t": ts.isoformat(timespec="seconds"),
                "equipment": equipment_id,
                "metric": "vibration_level",
                "value": round(0.40 + 0.45 * progress + _seed_float(f"v|{ts}", -0.03, 0.03), 4),
                "unit": "mm/s",
            }
        )
        operations.append(
            {
                "id": f"OP-{ts.strftime('%H%M')}-temp",
                "t": ts.isoformat(timespec="seconds"),
                "equipment": equipment_id,
                "metric": "bearing_temp",
                "value": round(55.0 + 18.0 * progress + _seed_float(f"t|{ts}", -1.5, 1.5), 4),
                "unit": "℃",
            }
        )
        operations.append(
            {
                "id": f"OP-{ts.strftime('%H%M')}-load",
                "t": ts.isoformat(timespec="seconds"),
                "equipment": equipment_id,
                "metric": "load_factor",
                "value": round(0.65 + 0.10 * progress + _seed_float(f"l|{ts}", -0.04, 0.04), 4),
                "unit": "",
            }
        )
    return operations


def _alarms(fault_day: date, equipment_id: str, equipment_name: str | None = None) -> list[dict]:
    """Pre/post-event 6h alarm flow with escalating severity."""
    base = datetime.combine(fault_day, time.min)
    fault_dt = base + timedelta(hours=8)
    label = equipment_name or equipment_id
    return [
        {
            "id": "ALM-0001",
            "time": (fault_dt - timedelta(hours=2)).isoformat(timespec="seconds"),
            "equipment_id": equipment_id,
            "equipment": label,
            "level": "info",
            "message": "振动达到提示阈值",
        },
        {
            "id": "ALM-0002",
            "time": (fault_dt - timedelta(minutes=45)).isoformat(timespec="seconds"),
            "equipment_id": equipment_id,
            "equipment": label,
            "level": "warning",
            "message": "振动超过预警阈值",
        },
        {
            "id": "ALM-0003",
            "time": (fault_dt - timedelta(minutes=5)).isoformat(timespec="seconds"),
            "equipment_id": equipment_id,
            "equipment": label,
            "level": "warning",
            "message": "轴承温度异常上升",
        },
        {
            "id": "ALM-0004",
            "time": fault_dt.isoformat(timespec="seconds"),
            "equipment_id": equipment_id,
            "equipment": label,
            "level": "critical",
            "message": "停机保护触发",
        },
        {
            "id": "ALM-0005",
            "time": (fault_dt + timedelta(minutes=30)).isoformat(timespec="seconds"),
            "equipment_id": equipment_id,
            "equipment": label,
            "level": "info",
            "message": "已切换至备用回路",
        },
    ]


def _work_orders(fault_day: date, equipment_id: str, equipment_name: str | None = None) -> list[dict]:
    label = equipment_name or equipment_id
    return [
        {
            "id": "WO-2026-0512",
            "title": "轴承点检（季度）",
            "status": "closed",
            "owner": "张三",
            "equipment_id": equipment_id,
            "equipment": label,
            "created_at": (fault_day - timedelta(days=7)).isoformat(),
            "closed_at": (fault_day - timedelta(days=5)).isoformat(),
            "note": "点检完成，未发现异常磨损",
        },
        {
            "id": "WO-2026-0521",
            "title": "振动传感器复测",
            "status": "in_progress",
            "owner": "李四",
            "equipment_id": equipment_id,
            "equipment": label,
            "created_at": (fault_day - timedelta(days=2)).isoformat(),
            "closed_at": None,
            "note": "复测进行中，下一次报告 24h 内提交",
        },
        {
            "id": "WO-2026-0523",
            "title": "故障应急响应",
            "status": "open",
            "owner": "王五",
            "equipment_id": equipment_id,
            "equipment": label,
            "created_at": fault_day.isoformat(),
            "closed_at": None,
            "note": "停机保护触发后开 work order，等待诊断结论",
        },
    ]


def _maintenance_records(fault_day: date, equipment_id: str, equipment_name: str | None = None) -> list[dict]:
    label = equipment_name or equipment_id
    return [
        {
            "id": "MR-2026-0418",
            "type": "oil_change",
            "equipment_id": equipment_id,
            "equipment": label,
            "at": (fault_day - timedelta(days=30)).isoformat(),
            "owner": "赵六",
            "note": "按 6 个月周期换油",
        },
        {
            "id": "MR-2026-0501",
            "type": "vibration_calibration",
            "equipment_id": equipment_id,
            "equipment": label,
            "at": (fault_day - timedelta(days=17)).isoformat(),
            "owner": "李四",
            "note": "振动传感器零点漂移校正",
        },
    ]


def main() -> int:
    parser = base_parser("Fault-context demo data")
    parser.add_argument("--fault-time", required=True, help="YYYY-MM-DD")
    parser.add_argument("--equipment-id", required=True)
    parser.add_argument("--equipment-name", default="", help="Equipment name (falls back to ID when empty)")
    parser.add_argument("--symptom", default="")
    parser.add_argument("--include-related-equipment", action="store_true")
    args = parser.parse_args()

    try:
        fault_day = date.fromisoformat(args.fault_time)
    except ValueError as exc:
        return emit_error("INVALID_FAULT_TIME", str(exc))

    eq_id = args.equipment_id.strip()
    if not eq_id:
        return emit_error("INVALID_EQUIPMENT_ID", "--equipment-id must be non-empty")
    eq_name = (args.equipment_name or "").strip() or None

    result = fetch_with_fallback(
        source="fault_context",
        fetch_args={
            "fault_time": args.fault_time,
            "equipment_id": eq_id,
            "equipment_name": eq_name,
            "symptom": args.symptom,
            "include_related_equipment": bool(args.include_related_equipment),
        },
    )
    payload = result.data

    output = {
        "schema_version": SCHEMA_VERSION,
        "fault_time": args.fault_time,
        "equipment_id": eq_id,
        "equipment_name": eq_name or eq_id,
        "symptom": args.symptom,
        "include_related": bool(args.include_related_equipment),
        "data_source": result.data_source,
        "operations": payload.get("operations") or [],
        "alarms": payload.get("alarms") or [],
        "work_orders": payload.get("work_orders") or [],
        "maintenance_records": payload.get("maintenance_records") or [],
        "related_equipment": payload.get("related_equipment") or [],
        "_meta": {"stub": True, "generated_at": iso_now(), "provider_notes": result.notes},
    }

    write_json(Path(args.output_dir), "fault_context", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
