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
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "daily_data.json"
EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
KPI_KEY_PATTERN = re.compile(r"^[a-z_]+$")

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}

KPI_UNITS = {
    "runtime_rate": "%",
    "downtime_count": "次",
    "alarm_count": "条",
    "output": "件",
    "energy_consumption": "kWh",
    "corrosion_rate": "mm/a",
    "thickness_loss": "mm",
    "vibration_level": "mm/s",
    "bearing_temp": "℃",
    "flow_rate": "m³/h",
    "outlet_pressure": "MPa",
    "valve_temp": "℃",
    "vibration_velocity_rms": "mm/s",
    "vibration_acceleration_peak": "m/s²",
    "kurtosis_index": "—",
}


def _output_dir() -> Path:
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


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
    import importlib.util as _ilu
    import sys as _sys
    from pathlib import Path as _Path

    def _load_script_module(name: str):
        module = _sys.modules.get(name)
        if module is not None:
            return module
        spec = _ilu.spec_from_file_location(name, script_dir / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"failed to load local script module: {name}")
        module = _ilu.module_from_spec(spec)
        _sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            if _sys.modules.get(name) is module:
                del _sys.modules[name]
            raise
        return module

    script_dir = _Path(__file__).parent
    dp = _load_script_module("_data_providers")
    _load_script_module("_data_provider_impls")

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


def _resolve_equipment_by_scope(eq_type: str, scope: str, scope_filter: str) -> list[dict]:
    """Resolve equipment from type+scope+filter using list_equipment logic.

    Returns full equipment dicts (id, name, area, sub_type, org_type) so callers
    can propagate metadata into per_equipment entries.
    """
    module = _load_list_equipment()
    if module is None:
        return []
    result = module.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])


def _load_list_equipment():
    script_dir = Path(__file__).parent
    list_eq_path = script_dir / "list_equipment.py"
    if not list_eq_path.exists():
        return None
    module = sys.modules.get("list_equipment")
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location("list_equipment", list_eq_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["list_equipment"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get("list_equipment") is module:
            del sys.modules["list_equipment"]
        return None
    return module


def _detect_equipment_type(equipment_ids: list[str]) -> str:
    """Derive ``eq_type`` from the org tree so pump/temperature KPI mappings apply.

    When the user passes ``--equipment`` directly, the CLI defaults to
    ``eq_type="all"``, which causes KPI specs (e.g. ``bearing_temp``) to use
    their generic position_type/series filters. For pumps, those generic
    filters point to 8k/9k rotating-machinery points while the actual
    temperature data lives in 2k — the pump-specific overrides never engage.

    Returns the common ``org_type`` when all given equipment share it,
    otherwise ``"all"``.
    """
    if not equipment_ids:
        return "all"
    module = _load_list_equipment()
    if module is None:
        return "all"
    user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID")
    if not user_id:
        return "all"
    try:
        org_result = module._query_from_org_tree(user_id, "all", "specific", ",".join(equipment_ids))
    except Exception:
        return "all"
    if org_result is None:
        return "all"
    devices = org_result.get("equipment", [])
    if not devices:
        return "all"
    org_types = {d.get("org_type") for d in devices}
    if len(org_types) == 1:
        return org_types.pop()
    return "all"


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
    invalid_format = [item for item in kpi_keys if not KPI_KEY_PATTERN.fullmatch(item)]
    if invalid_format:
        return "--kpis contains invalid KPI key(s): " + ",".join(invalid_format)
    unsupported = [item for item in kpi_keys if item not in KPI_UNITS]
    if unsupported:
        return "--kpis contains unsupported KPI key(s): " + ",".join(unsupported)
    return None


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


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
    args = parser.parse_args()

    try:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            return _error(f"invalid --date: {exc}")

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
            include_per_equipment = len(equipment_ids) > 20
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
            include_per_equipment = False
            is_scope_mode = False
            # When --type is not explicitly overridden, derive it from the org
            # tree so per-type KPI mappings (e.g. pump bearing_temp → 2k) apply.
            if getattr(args, "type") == "all":
                detected = _detect_equipment_type(equipment_ids)
                if detected != "all":
                    eq_type = detected

        kpi_keys = _dedupe_preserve_order(_parse_csv(args.kpis) or ["runtime_rate", "downtime_count", "alarm_count"])
        kpi_error = _validate_kpi_keys(kpi_keys)
        if kpi_error:
            return _error(kpi_error)

        result = build_result(args.date, equipment_ids, kpi_keys, args.compare, eq_type, include_per_equipment, is_scope_mode, equipment_meta)
        out_path = write_payload(result)
        print(json.dumps({"output": str(out_path), "report_date": result["report_date"]}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - report to stdout per Skill convention
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
