#!/usr/bin/env python
"""Query daily report data for ai-report--daily agent.

Output contract (design doc §6.1): writes JSON to
``$DAILY_REPORT_OUTPUT_DIR/daily_data.json`` (default
``/mnt/user-data/outputs/daily_data.json``) with shape::

    {
      "report_date": "2026-05-13",
      "equipment_ids": ["E001"],
      "kpi_keys": ["runtime_rate", ...],
      "compare_type": "previous_day" | "previous_week" | "none",
      "compare_date": "2026-05-12" | null,
      "current": {
        "kpis": {<key>: <value>},
        "kpi_units": {<key>: <unit>},
        "hourly_runtime_rate": [24 floats],
        "alarms": [{time, equipment, level, message}],
        "per_equipment": {<id>: {kpis, hourly_runtime_rate}} (only when >20 devices)
      },
      "compare": <same as current> | null,
      "data_source": "ins",
      "data_notes": [],
    }

Data is always fetched from the InS-backed provider. Any failure
(``HttpProviderError`` from missing features-tool / KPI mapping gap /
empty trend / auth) propagates as ``{"error": ...}`` on stdout.
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
    KPI_UNITS,
    VALID_SCOPES,
    VALID_TYPES,
    _ARGPARSE_DEFAULT_KPIS,
    _EQUIPMENT_TYPE_DEFAULT_KPIS,
    dedupe_preserve_order,
    detect_equipment_type,
    error_output,
    load_sibling_module,
    parse_csv,
    resolve_equipment_by_scope,
    validate_equipment_ids,
    validate_kpi_keys,
)

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "daily_data.json"


def _output_dir() -> Path:
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _runtime_data_dir(output_dir: str | None) -> Path | None:
    """Map runtime ``--output-dir`` roots to the platform's ``data/`` subdir."""
    if not output_dir:
        return None
    return Path(output_dir) / "data"


def fetch_day(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    include_per_equipment: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Return one-day payload via the InS provider.

    Backward-compatible signature for weekly/monthly aggregators and tests
    that treat the return value as a flat dict. To capture ``data_source``
    / ``data_notes`` use :func:`fetch_day_with_provenance` instead.
    """
    data, _, _ = fetch_day_with_provenance(
        date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
    )
    return data


def fetch_day_with_provenance(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    include_per_equipment: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> tuple[dict, str, list[str]]:
    """Provider-aware variant of :func:`fetch_day`.

    Calls the registered ``daily`` provider (``InsDailyProvider``) directly.
    Any ``HttpProviderError`` propagates so the CLI surfaces it as
    ``{"error": "HttpProviderError: ..."}`` instead of masking with demo
    output.
    """
    dp = load_sibling_module("_data_providers")
    load_sibling_module("_data_provider_impls")

    provider = dp.get_provider("daily")
    result = provider.fetch(
        date_str=date_str,
        equipment_ids=equipment_ids,
        kpi_keys=kpi_keys,
        eq_type=eq_type,
        include_per_equipment=include_per_equipment,
        equipment_meta=equipment_meta,
    )
    if not isinstance(result, dp.ProviderResult):
        raise TypeError(f"daily provider returned non-ProviderResult: {type(result)}")
    return result.data, result.data_source, list(result.notes)


def _compare_date(date_str: str, compare: str) -> str | None:
    if compare == "previous_day":
        return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if compare == "previous_week":
        return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    return None


def build_result(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    compare: str,
    eq_type: str = "all",
    include_per_equipment: bool = False,
    is_scope_mode: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    compare = compare or "none"
    current, current_src, current_notes = fetch_day_with_provenance(
        date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
    )
    compare_date_str = _compare_date(date_str, compare)
    if compare_date_str:
        compare_block, compare_src, compare_notes = fetch_day_with_provenance(
            compare_date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
        )
    else:
        compare_block, compare_src, compare_notes = None, None, []

    notes: list[str] = list(current_notes)
    if compare_src is not None:
        notes.extend(compare_notes)
    data_source = current_src

    equipment_names: dict[str, str] = {}
    if equipment_meta:
        equipment_names = {eid: meta.get("name", eid) for eid, meta in equipment_meta.items() if meta}
    result: dict = {
        "report_date": date_str,
        "equipment_ids": equipment_ids,
        "equipment_names": equipment_names,
        "kpi_keys": kpi_keys,
        "compare_type": compare,
        "compare_date": compare_date_str,
        "current": current,
        "compare": compare_block,
        "data_source": data_source,
        "data_notes": notes,
    }
    if is_scope_mode:
        result["equipment_type"] = eq_type
        result["equipment_count"] = len(equipment_ids)
    return result


def write_payload(result: dict, output_dir: Path | None = None) -> Path:
    out_dir = output_dir or _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Query daily report data")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--equipment", default="", help="Comma-separated equipment ids")
    parser.add_argument(
        "--equipment-names",
        dest="equipment_names",
        default="",
        help="Comma-separated equipment names aligned with --equipment (optional)",
    )
    parser.add_argument(
        "--kpis",
        default="runtime_rate,downtime_count,alarm_count",
        help="Comma-separated KPI keys",
    )
    parser.add_argument(
        "--compare",
        default="previous_day",
        choices=["previous_day", "previous_week", "none"],
    )
    parser.add_argument("--type", default="all", help="Equipment type filter")
    parser.add_argument("--scope", default=None, help="Scope: all/area/specific")
    parser.add_argument("--scope-filter", default="", help="Area names or equipment IDs for scope")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional runtime output root; payload is written under <output-dir>/data/",
    )
    args = parser.parse_args()

    try:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            return error_output(f"invalid --date: {exc}")

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
            include_per_equipment = len(equipment_ids) > 20
            is_scope_mode = True
            # When --type is all, derive eq_type from resolved equipment so
            # per-type KPI mappings (e.g. pump → 2K) apply in scope mode too.
            if eq_type == "all" and equipment_records:
                org_types = {e.get("org_type") for e in equipment_records if e.get("org_type")}
                if len(org_types) == 1:
                    eq_type = org_types.pop()
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
            include_per_equipment = False
            is_scope_mode = False
            # When --type is not explicitly overridden, derive it from the org
            # tree so per-type KPI mappings (e.g. pump bearing_temp → 2k) apply.
            if getattr(args, "type") == "all":
                detected = _detect_equipment_type(equipment_ids)
                if detected != "all":
                    eq_type = detected

        kpi_keys = dedupe_preserve_order(parse_csv(args.kpis) or ["runtime_rate", "downtime_count", "alarm_count"])
        # When --kpis is left at its argparse default and eq_type is a specific
        # type, substitute type-appropriate KPIs.  This is load-bearing for pumps:
        # the defaults (runtime_rate / downtime_count / alarm_count) only match
        # 8K/9K position types, so 2K pump data returns empty without this swap.
        if kpi_keys == _ARGPARSE_DEFAULT_KPIS and eq_type != "all" and eq_type in _EQUIPMENT_TYPE_DEFAULT_KPIS:
            kpi_keys = list(_EQUIPMENT_TYPE_DEFAULT_KPIS[eq_type])
        kpi_error = validate_kpi_keys(kpi_keys, KPI_UNITS)
        if kpi_error:
            return error_output(kpi_error)

        result = build_result(args.date, equipment_ids, kpi_keys, args.compare, eq_type, include_per_equipment, is_scope_mode, equipment_meta)
        out_path = write_payload(result, _runtime_data_dir(args.output_dir))
        print(json.dumps({"output": str(out_path), "report_date": result["report_date"]}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - report to stdout per Skill convention
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


# Backward-compat alias for tests that monkeypatch the old local name
_detect_equipment_type = detect_equipment_type


if __name__ == "__main__":
    sys.exit(main())
