#!/usr/bin/env python
"""Query weekly report data for ai-report--weekly agent.

Output contract (design doc §6.1): writes JSON to
``$WEEKLY_REPORT_OUTPUT_DIR/weekly_data.json`` (default
``/mnt/user-data/outputs/weekly_data.json``) with shape::

    {
      "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
      "equipment_ids": ["RM-001"],
      "kpi_keys": ["runtime_rate", ...],
      "compare_type": "previous_week" | "previous_year" | "none",
      "compare_period": {"start": "...", "end": "..."} | null,
      "current": {
        "daily": [{date, kpis, kpi_units, alarms}, ...],   # 7 entries
        "aggregated": {kpis_mean, kpis_max, kpis_min, kpis_std},
        "alarms": [...],                                    # union of daily alarms
      },
      "compare": <same shape as current> | null,
      "data_source": "ins",
      "week_start_warning": "..." | null,
      "compare_warning": "..." | null,
    }

Data is fetched from the InS-backed daily provider on a per-day basis and
aggregated into the weekly shape. Any failure (``HttpProviderError``)
propagates as ``{"error": ...}`` on stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "weekly_data.json"
EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
KPI_KEY_PATTERN = re.compile(r"^[a-z_]+$")

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}
VALID_COMPARES = {"previous_week", "previous_year", "none"}

DAY_COUNT = 7
DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]


def _output_dir() -> Path:
    return Path(os.environ.get("WEEKLY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _load_query_daily():
    """Load the sibling query_daily module to reuse its demo data generator."""
    module = sys.modules.get("query_daily")
    if module is not None:
        return module
    script_dir = Path(__file__).parent
    qd_path = script_dir / "query_daily.py"
    if not qd_path.exists():
        raise RuntimeError(f"query_daily.py not found beside query_weekly.py at {qd_path}")
    spec = importlib.util.spec_from_file_location("query_daily", qd_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to build spec for query_daily")
    module = importlib.util.module_from_spec(spec)
    sys.modules["query_daily"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get("query_daily") is module:
            del sys.modules["query_daily"]
        raise
    return module


def _load_list_equipment():
    module = sys.modules.get("list_equipment")
    if module is not None:
        return module
    script_dir = Path(__file__).parent
    le_path = script_dir / "list_equipment.py"
    if not le_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("list_equipment", le_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["list_equipment"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get("list_equipment") is module:
            del sys.modules["list_equipment"]
        raise
    return module


def _is_monday(date_str: str) -> bool:
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() == 0


def _week_range(week_start: str) -> tuple[str, str]:
    start = datetime.strptime(week_start, "%Y-%m-%d")
    end = start + timedelta(days=DAY_COUNT - 1)
    return week_start, end.strftime("%Y-%m-%d")


def _previous_period(week_start: str, compare: str) -> tuple[str, str] | None:
    if compare == "previous_week":
        prev_start = datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=DAY_COUNT)
    elif compare == "previous_year":
        prev_start = datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=365)
    else:
        return None
    return _week_range(prev_start.strftime("%Y-%m-%d"))


def _has_previous_year_data(week_start: str) -> bool:
    """Demo policy: if requested start is >180 days from "today" assume no data.

    This makes ``--compare previous_year`` deterministic in tests while leaving
    a hook for real connectors to override. Real implementations will plug a
    catalog probe in here.
    """
    # When prev year start would land before 2025-01-01, treat as missing in
    # demo mode — that boundary matches the demo project's data horizon.
    prev_year_start = datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=365)
    return prev_year_start >= datetime(2025, 1, 1)


def fetch_week(
    week_start: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    aggregate: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Return one-week payload (backward-compatible flat dict).

    Calls :func:`fetch_week_with_provenance` and discards the data_source /
    notes tuple so existing tests and callers that only need the payload
    keep working unchanged.
    """
    data, _, _ = fetch_week_with_provenance(
        week_start, equipment_ids, kpi_keys, eq_type, aggregate, equipment_meta
    )
    return data


def fetch_week_with_provenance(
    week_start: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    aggregate: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> tuple[dict, str, list[str]]:
    """Provider-aware variant of :func:`fetch_week`.

    Composes the 7-day window from per-day calls to
    :func:`query_daily.fetch_day_with_provenance` so the existing weekly
    aggregation logic keeps owning the shape (``daily[]`` + ``aggregated``).
    Each per-day call resolves to the InS-backed daily provider; any
    ``HttpProviderError`` propagates so the CLI surfaces the failure.
    """
    query_daily = _load_query_daily()
    start_dt = datetime.strptime(week_start, "%Y-%m-%d")

    daily_entries: list[dict] = []
    union_alarms: list[dict] = []
    sources: set[str] = set()
    notes: list[str] = []
    for offset in range(DAY_COUNT):
        date_str = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        day_payload, day_src, day_notes = query_daily.fetch_day_with_provenance(
            date_str,
            equipment_ids,
            kpi_keys,
            eq_type,
            False,
            equipment_meta,
        )
        sources.add(day_src)
        for note in day_notes:
            tagged = f"[{date_str}] {note}"
            if tagged not in notes:
                notes.append(tagged)
        entry = {
            "date": date_str,
            "kpis": day_payload.get("kpis", {}),
            "kpi_units": day_payload.get("kpi_units", {}),
            "alarms": day_payload.get("alarms", []),
        }
        daily_entries.append(entry)
        union_alarms.extend(entry["alarms"])

    aggregated = _aggregate_daily(daily_entries, kpi_keys)
    result: dict = {
        "daily": [] if aggregate else daily_entries,
        "aggregated": aggregated,
        "alarms": union_alarms,
    }
    if aggregate:
        # Even in aggregate mode keep one canonical kpi_units map so weekly_kpi
        # can render units without re-scanning daily list.
        result["kpi_units"] = daily_entries[0].get("kpi_units", {}) if daily_entries else {}

    # All days come from the same InS provider; mismatch can only happen if
    # one of the days returns no `data_source` at all, which would be a
    # programming bug — surface it loudly rather than silently coercing.
    if len(sources) != 1:
        raise RuntimeError(
            f"unexpected per-day data_source mismatch ({sorted(sources)}); "
            "InS provider should always tag results as 'ins'"
        )
    data_source = next(iter(sources))
    return result, data_source, notes


def _aggregate_daily(daily_entries: list[dict], kpi_keys: list[str]) -> dict:
    kpis_mean: dict[str, float] = {}
    kpis_max: dict[str, float] = {}
    kpis_min: dict[str, float] = {}
    kpis_std: dict[str, float] = {}
    for key in kpi_keys:
        values: list[float] = []
        for entry in daily_entries:
            v = entry.get("kpis", {}).get(key)
            if v is None:
                continue
            if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                values.append(float(v))
        if not values:
            continue
        mean = sum(values) / len(values)
        kpis_mean[key] = round(mean, 4)
        kpis_max[key] = round(max(values), 4)
        kpis_min[key] = round(min(values), 4)
        if len(values) > 1:
            variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            kpis_std[key] = round(math.sqrt(variance), 4)
        else:
            kpis_std[key] = 0.0
    return {
        "kpis_mean": kpis_mean,
        "kpis_max": kpis_max,
        "kpis_min": kpis_min,
        "kpis_std": kpis_std,
    }


def _resolve_equipment_by_scope(eq_type: str, scope: str, scope_filter: str) -> list[dict]:
    """Resolve equipment using list_equipment.query_equipment, same as daily."""
    list_eq = _load_list_equipment()
    if list_eq is None:
        return []
    result = list_eq.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])


def build_result(
    week_start: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    compare: str,
    eq_type: str = "all",
    aggregate: bool = False,
    is_scope_mode: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Build the full payload matching design doc §6.1."""
    compare = compare or "none"
    if compare not in VALID_COMPARES:
        raise ValueError(f"invalid compare: {compare}")

    week_end = _week_range(week_start)[1]
    auto_aggregate = aggregate or (is_scope_mode and len(equipment_ids) > 50)
    current, current_src, current_notes = fetch_week_with_provenance(
        week_start, equipment_ids, kpi_keys, eq_type, auto_aggregate, equipment_meta
    )

    compare_period: dict | None = None
    compare_block: dict | None = None
    compare_warning: str | None = None
    compare_src: str | None = None
    compare_notes: list[str] = []
    prev_range = _previous_period(week_start, compare)
    if prev_range:
        if compare == "previous_year" and not _has_previous_year_data(week_start):
            compare_warning = "去年同期数据不可用，已跳过同比"
        else:
            compare_period = {"start": prev_range[0], "end": prev_range[1]}
            compare_block, compare_src, compare_notes = fetch_week_with_provenance(
                prev_range[0], equipment_ids, kpi_keys, eq_type, auto_aggregate, equipment_meta
            )

    notes: list[str] = list(current_notes)
    if compare_src is not None:
        notes.extend(f"[compare] {note}" for note in compare_notes)
    data_source = current_src

    equipment_names: dict[str, str] = {}
    if equipment_meta:
        equipment_names = {eid: meta.get("name", eid) for eid, meta in equipment_meta.items() if meta}

    result: dict = {
        "report_period": {
            "week_start": week_start,
            "week_end": week_end,
            "day_count": DAY_COUNT,
        },
        "equipment_ids": equipment_ids,
        "equipment_names": equipment_names,
        "kpi_keys": kpi_keys,
        "compare_type": compare,
        "compare_period": compare_period,
        "current": current,
        "compare": compare_block,
        "data_source": data_source,
        "data_notes": notes,
    }
    if not _is_monday(week_start):
        result["week_start_warning"] = "未对齐自然周一,已按所选日期为锚取 7 天窗口"
    else:
        result["week_start_warning"] = None
    if compare_warning:
        result["compare_warning"] = compare_warning
    else:
        result["compare_warning"] = None
    if is_scope_mode:
        result["equipment_type"] = eq_type
        result["equipment_count"] = len(equipment_ids)
    if auto_aggregate:
        result["aggregate_mode"] = "aggregated"
    else:
        result["aggregate_mode"] = "detail"
    return result


def write_payload(result: dict) -> Path:
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _validate_equipment_ids(equipment_ids: list[str]) -> str | None:
    if not equipment_ids:
        return "--equipment must be a non-empty CSV"
    invalid = [item for item in equipment_ids if not EQUIPMENT_ID_PATTERN.fullmatch(item)]
    if invalid:
        return "--equipment contains invalid equipment id(s): " + ",".join(invalid)
    return None


def _validate_kpi_keys(kpi_keys: list[str]) -> str | None:
    if not kpi_keys:
        return "--kpis must include at least one KPI key"
    invalid = [item for item in kpi_keys if not KPI_KEY_PATTERN.fullmatch(item)]
    if invalid:
        return "--kpis contains invalid KPI key(s): " + ",".join(invalid)
    return None


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Query weekly report data")
    parser.add_argument("--week-start", required=True, help="Week start date YYYY-MM-DD (recommended Monday)")
    parser.add_argument("--equipment", default="", help="Comma-separated equipment ids")
    parser.add_argument(
        "--equipment-names",
        dest="equipment_names",
        default="",
        help="Comma-separated equipment names aligned with --equipment (optional)",
    )
    parser.add_argument(
        "--kpis",
        default=",".join(DEFAULT_KPIS),
        help="Comma-separated KPI keys",
    )
    parser.add_argument(
        "--compare",
        default="previous_week",
        choices=sorted(VALID_COMPARES),
    )
    parser.add_argument("--type", default="all", help="Equipment type filter")
    parser.add_argument("--scope", default=None, help="Scope: all/area/specific")
    parser.add_argument("--scope-filter", default="", help="Area names or equipment IDs for scope")
    parser.add_argument("--aggregate", action="store_true", help="Force aggregate mode (skip per-day detail)")
    args = parser.parse_args()

    try:
        try:
            datetime.strptime(args.week_start, "%Y-%m-%d")
        except ValueError as exc:
            return _error(f"invalid --week-start: {exc}")

        eq_type = getattr(args, "type")
        if eq_type not in VALID_TYPES:
            return _error(f"--type must be one of {sorted(VALID_TYPES)}, got: {eq_type}")

        scope = args.scope

        if scope is not None:
            if scope not in VALID_SCOPES:
                return _error(f"--scope must be one of {sorted(VALID_SCOPES)}, got: {scope}")
            equipment_records = _resolve_equipment_by_scope(eq_type, scope, getattr(args, "scope_filter", ""))
            if not equipment_records:
                return _error("no equipment matched for the given --type/--scope/--scope-filter")
            equipment_ids = [e["id"] for e in equipment_records]
            equipment_meta = {e["id"]: e for e in equipment_records}
            is_scope_mode = True
        else:
            equipment_ids = _dedupe_preserve_order(_parse_csv(args.equipment))
            equipment_error = _validate_equipment_ids(equipment_ids)
            if equipment_error:
                return _error(equipment_error)
            equipment_names = _parse_csv(args.equipment_names)
            equipment_meta = None
            if equipment_names:
                equipment_meta = {
                    eid: {"id": eid, "name": (equipment_names[i] if i < len(equipment_names) else eid)}
                    for i, eid in enumerate(equipment_ids)
                }
            is_scope_mode = False

        kpi_keys = _dedupe_preserve_order(_parse_csv(args.kpis) or list(DEFAULT_KPIS))
        kpi_error = _validate_kpi_keys(kpi_keys)
        if kpi_error:
            return _error(kpi_error)

        result = build_result(
            week_start=args.week_start,
            equipment_ids=equipment_ids,
            kpi_keys=kpi_keys,
            compare=args.compare,
            eq_type=eq_type,
            aggregate=args.aggregate,
            is_scope_mode=is_scope_mode,
            equipment_meta=equipment_meta,
        )
        out_path = write_payload(result)
        print(
            json.dumps(
                {
                    "output": str(out_path),
                    "week_start": result["report_period"]["week_start"],
                    "week_end": result["report_period"]["week_end"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - report to stdout per Skill convention
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
