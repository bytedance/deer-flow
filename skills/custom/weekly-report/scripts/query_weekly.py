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

Data is fetched from the platform bridge on a per-day basis and
aggregated into the weekly shape. Any failure (``HttpProviderError``)
propagates as ``{"error": ...}`` on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _report_common import (
    VALID_SCOPES,
    VALID_TYPES,
    aggregate_kpis,
    dedupe_preserve_order,
    detect_equipment_type,
    error_output,
    has_previous_year_data_weekly,
    load_sibling_module,
    parse_csv,
    resolve_equipment_by_scope,
    validate_equipment_ids,
    validate_kpi_keys,
)

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "weekly_data.json"

VALID_COMPARES = {"previous_week", "previous_year", "none"}

DAY_COUNT = 7
DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]


def _output_dir() -> Path:
    return Path(os.environ.get("WEEKLY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _runtime_data_dir(output_dir: str | None) -> Path | None:
    """Map runtime ``--output-dir`` roots to the platform's ``data/`` subdir."""
    if not output_dir:
        return None
    return Path(output_dir) / "data"


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

    Fetches the 7-day window through the platform bridge so the weekly
    aggregation logic keeps owning the shape (``daily[]`` + ``aggregated``).
    Any ``HttpProviderError`` propagates so the CLI surfaces the failure.
    """
    dp = load_sibling_module("_data_providers")
    load_sibling_module("_data_provider_impls")

    provider = dp.get_provider("weekly")
    result = provider.fetch(
        week_start=week_start,
        equipment_ids=equipment_ids,
        kpi_keys=kpi_keys,
        eq_type=eq_type,
        aggregate=aggregate,
        equipment_meta=equipment_meta,
    )
    if not isinstance(result, dp.ProviderResult):
        raise TypeError(f"weekly provider returned non-ProviderResult: {type(result)}")

    daily_entries = result.data["daily_entries"]
    union_alarms: list[dict] = []
    for entry in daily_entries:
        union_alarms.extend(entry.get("alarms", []))

    aggregated = aggregate_kpis(daily_entries, kpi_keys)
    result_dict: dict = {
        "daily": [] if aggregate else daily_entries,
        "aggregated": aggregated,
        "alarms": union_alarms,
    }
    if aggregate:
        result_dict["kpi_units"] = daily_entries[0].get("kpi_units", {}) if daily_entries else {}

    return result_dict, result.data_source, list(result.notes)


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
        if compare == "previous_year" and not has_previous_year_data_weekly(week_start):
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


def write_payload(result: dict, output_dir: Path | None = None) -> Path:
    out_dir = output_dir or _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


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
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional runtime output root; payload is written under <output-dir>/data/",
    )
    args = parser.parse_args()

    try:
        try:
            datetime.strptime(args.week_start, "%Y-%m-%d")
        except ValueError as exc:
            return error_output(f"invalid --week-start: {exc}")

        eq_type = getattr(args, "type")
        if eq_type not in VALID_TYPES:
            return error_output(f"--type must be one of {sorted(VALID_TYPES)}, got: {eq_type}")

        scope = args.scope

        if scope is not None:
            if scope not in VALID_SCOPES:
                return error_output(f"--scope must be one of {sorted(VALID_SCOPES)}, got: {scope}")
            equipment_records = resolve_equipment_by_scope(eq_type, scope, getattr(args, "scope_filter", ""))
            if not equipment_records:
                return error_output("no equipment matched for the given --type/--scope/--scope-filter")
            equipment_ids = [e["id"] for e in equipment_records]
            equipment_meta = {e["id"]: e for e in equipment_records}
            is_scope_mode = True
        else:
            equipment_ids = dedupe_preserve_order(parse_csv(args.equipment))
            equipment_error = validate_equipment_ids(equipment_ids)
            if equipment_error:
                return error_output(equipment_error)
            equipment_names = parse_csv(args.equipment_names)
            equipment_meta = None
            if equipment_names:
                equipment_meta = {
                    eid: {"id": eid, "name": (equipment_names[i] if i < len(equipment_names) else eid)}
                    for i, eid in enumerate(equipment_ids)
                }
            is_scope_mode = False
            # When --type is not explicitly overridden, derive it from the org
            # tree so per-type KPI mappings (e.g. pump bearing_temp → 2k) apply.
            if getattr(args, "type") == "all":
                detected = detect_equipment_type(equipment_ids)
                if detected != "all":
                    eq_type = detected

        kpi_keys = dedupe_preserve_order(parse_csv(args.kpis) or list(DEFAULT_KPIS))
        kpi_error = validate_kpi_keys(kpi_keys)
        if kpi_error:
            return error_output(kpi_error)

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
        out_path = write_payload(result, _runtime_data_dir(args.output_dir))
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
