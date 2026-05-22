#!/usr/bin/env python
"""Query monthly report data for ai-report--monthly agent.

Output contract (design doc §6.1): writes JSON to
``$MONTHLY_REPORT_OUTPUT_DIR/monthly_data.json`` (falling back to
``$WEEKLY_REPORT_OUTPUT_DIR`` and ``$DAILY_REPORT_OUTPUT_DIR``, then to
``/mnt/user-data/outputs/monthly_data.json``).

Shape::

    {
      "report_period": {report_month, month_start, month_end, day_count, week_buckets[]},
      "equipment_ids": [...],
      "kpi_keys": [...],
      "compare_types": ["previous_month", "previous_year_month"],
      "compare_periods": {<basis>: {start, end}},
      "current": {weekly[], aggregated, maintenance, alarms, critical_events, improvement_tracking},
      "compare": {<basis>: {weekly, aggregated, maintenance, alarms} | null},
      "data_source": "ins",
      "compare_warning": "..." | null,
    }

Data is fetched from the InS-backed daily provider on a per-day basis and
aggregated into the monthly shape. Any failure (``HttpProviderError``)
propagates as ``{"error": ...}`` on stdout.

Key contracts (see design doc + sprint plan):
- Uses ``calendar.monthrange(year, month)`` for day_count (handles 2/29).
- ``week_buckets`` are month-anchored 7-day buckets (NOT ISO weeks):
  W1 starts at month_start, every 7 days, last bucket truncates at month_end.
  Never uses ``datetime.isocalendar()``.
- ``--compare`` is CSV (multi-baseline). ``none`` is exclusive.
- ``maintenance.total_uptime_hours`` is computed as
  ``day_count * 24 - total_downtime_minutes / 60`` and is emitted by this
  script (not derived downstream).
"""

from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure sibling helper modules resolve when this file is imported via
# importlib.util (e.g., by query_diagnosis.py) where sys.path[0] may not be
# this script's parent directory.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Default target thresholds for达标率 computation.
# These are reference configuration values (not per-run demo data).
# ---------------------------------------------------------------------------

def _default_targets() -> dict[str, dict]:
    return {
        "runtime_rate": {"min": 0.85},
        "vibration_level": {"max": 4.0},
        "outlet_pressure": {"min": 0.7, "max": 1.5},
        "bearing_temp": {"max": 75.0},
    }


def _compute_maintenance(daily_entries: list[dict], day_count: int) -> dict:
    """Compute maintenance stats from real KPI data.

    Uses ``alarm_count`` for failure counts and ``runtime_rate`` for
    uptime/downtime. Falls back to null when those KPIs weren't fetched.
    """
    total_failures = 0
    runtime_rates: list[float] = []
    for entry in daily_entries:
        kpis = entry.get("kpis", {})
        ac = kpis.get("alarm_count")
        if ac is not None:
            total_failures += int(ac)
        rt = kpis.get("runtime_rate")
        if rt is not None:
            runtime_rates.append(rt)

    avg_runtime = sum(runtime_rates) / len(runtime_rates) if runtime_rates else None

    if avg_runtime is not None:
        total_uptime_hours = round(day_count * 24 * avg_runtime, 2)
        total_downtime_minutes = round(day_count * 24 * 60 * (1 - avg_runtime))
    else:
        total_uptime_hours = None
        total_downtime_minutes = None

    mtbf_hours = (
        round(total_uptime_hours / total_failures, 2)
        if (total_failures > 0 and total_uptime_hours is not None)
        else None
    )

    return {
        "total_failures": total_failures,
        "total_uptime_hours": total_uptime_hours,
        "total_downtime_minutes": total_downtime_minutes,
        "total_repair_minutes": None,
        "mtbf_hours": mtbf_hours,
        "mttr_hours": None,
    }

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "monthly_data.json"
EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
KPI_KEY_PATTERN = re.compile(r"^[a-z_]+$")
REPORT_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}
VALID_COMPARES = {"previous_month", "previous_year_month", "none"}

# Month-anchored bucket length. Never use ISO weeks.
BUCKET_DAYS = 7
DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]
# Special KPI keys that monthly always supports as derived metrics.
SPECIAL_KPIS = {"mtbf", "mttr", "target_rate"}


def _output_dir() -> Path:
    """Resolve output dir following monthly → weekly → daily → default fallback."""
    return Path(
        os.environ.get(
            "MONTHLY_REPORT_OUTPUT_DIR",
            os.environ.get(
                "WEEKLY_REPORT_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            ),
        )
    )


def _load_ins_provider():
    """Load the sibling InS provider module by file path (mirrors query_weekly)."""
    module = sys.modules.get("_ins_provider")
    if module is not None:
        return module
    script_dir = Path(__file__).parent
    provider_path = script_dir / "_ins_provider.py"
    if not provider_path.exists():
        raise RuntimeError(f"_ins_provider.py not found beside query_monthly.py at {provider_path}")
    spec = importlib.util.spec_from_file_location("_ins_provider", provider_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to build spec for _ins_provider")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ins_provider"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get("_ins_provider") is module:
            del sys.modules["_ins_provider"]
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


def _parse_report_month(value: str) -> tuple[int, int]:
    if not REPORT_MONTH_PATTERN.fullmatch(value):
        raise ValueError(f"invalid --report-month: {value} (expected YYYY-MM)")
    year, month = value.split("-")
    y, m = int(year), int(month)
    if not (2000 <= y <= 2100):
        raise ValueError(f"--report-month year out of range [2000, 2100]: {y}")
    if not (1 <= m <= 12):
        raise ValueError(f"--report-month month out of range [01, 12]: {m}")
    return y, m


def _month_bounds(year: int, month: int) -> tuple[str, str, int]:
    """Return (month_start, month_end, day_count). Uses calendar.monthrange for leap-year safety."""
    _, day_count = calendar.monthrange(year, month)
    start = datetime(year, month, 1)
    end = datetime(year, month, day_count)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), day_count


def _build_week_buckets(month_start: str, day_count: int) -> list[dict]:
    """Month-anchored 7-day buckets. W1 from month_start, W5 truncates at month_end.

    Never use ISO weeks — bucket boundaries are anchored to the natural month,
    not ISO weekdays.
    """
    start_dt = datetime.strptime(month_start, "%Y-%m-%d")
    buckets: list[dict] = []
    consumed = 0
    idx = 1
    while consumed < day_count:
        bucket_start = start_dt + timedelta(days=consumed)
        bucket_days = min(BUCKET_DAYS, day_count - consumed)
        bucket_end = bucket_start + timedelta(days=bucket_days - 1)
        buckets.append(
            {
                "label": f"W{idx}: {bucket_start.strftime('%m-%d')}~{bucket_end.strftime('%m-%d')}",
                "date_range": {
                    "start": bucket_start.strftime("%Y-%m-%d"),
                    "end": bucket_end.strftime("%Y-%m-%d"),
                },
                "day_count": bucket_days,
            }
        )
        consumed += bucket_days
        idx += 1
    return buckets


def _compare_month_bounds(year: int, month: int, basis: str) -> tuple[int, int]:
    """Return (year, month) of the comparison period."""
    if basis == "previous_month":
        if month == 1:
            return year - 1, 12
        return year, month - 1
    if basis == "previous_year_month":
        return year - 1, month
    raise ValueError(f"unsupported compare basis: {basis}")


def _has_previous_year_data(year: int, month: int) -> bool:
    """Demo policy: previous_year_month is available only if it lands on or after 2024-01.

    Mirrors the weekly script's 2025-01-01 horizon, shifted one year earlier so
    that 2025-Q1 monthly reports still have a YoY baseline. Real connectors will
    override this hook.
    """
    pyr, pmo = year - 1, month
    return datetime(pyr, pmo, 1) >= datetime(2024, 1, 1)


def _aggregate_kpis(daily_entries: list[dict], kpi_keys: list[str]) -> dict:
    """Compute mean/max/min/std across a list of {kpis: {...}} entries.

    Returns dict with kpis_mean / kpis_max / kpis_min / kpis_std.
    """
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


def _weighted_aggregate_from_weekly(weekly: list[dict], kpi_keys: list[str]) -> dict:
    """Aggregate weekly bucket means into month-level mean/max/min/std,
    weighted by each bucket's ``day_count`` for the mean.
    """
    kpis_mean: dict[str, float] = {}
    kpis_max: dict[str, float] = {}
    kpis_min: dict[str, float] = {}
    kpis_std: dict[str, float] = {}
    for key in kpi_keys:
        weighted_sum = 0.0
        total_weight = 0
        peak_vals: list[float] = []
        trough_vals: list[float] = []
        all_means: list[float] = []
        for bucket in weekly:
            mean = (bucket.get("kpis_mean") or {}).get(key)
            if mean is None:
                continue
            day_count = int(bucket.get("date_range_day_count") or bucket.get("day_count") or 0)
            if day_count <= 0:
                continue
            weighted_sum += float(mean) * day_count
            total_weight += day_count
            all_means.append(float(mean))
            peak_vals.append(float((bucket.get("kpis_max") or {}).get(key, mean)))
            trough_vals.append(float((bucket.get("kpis_min") or {}).get(key, mean)))
        if total_weight == 0 or not all_means:
            continue
        month_mean = weighted_sum / total_weight
        kpis_mean[key] = round(month_mean, 4)
        kpis_max[key] = round(max(peak_vals), 4)
        kpis_min[key] = round(min(trough_vals), 4)
        if len(all_means) > 1:
            variance = sum((v - month_mean) ** 2 for v in all_means) / (len(all_means) - 1)
            kpis_std[key] = round(math.sqrt(variance), 4)
        else:
            kpis_std[key] = 0.0
    return {
        "kpis_mean": kpis_mean,
        "kpis_max": kpis_max,
        "kpis_min": kpis_min,
        "kpis_std": kpis_std,
    }


def _kpis_target_rate(daily_entries: list[dict], kpi_keys: list[str], targets: dict[str, dict]) -> dict[str, float]:
    """Per-KPI "days within target / total days" ratio.

    ``targets[key]`` is expected to be ``{min: x, max: y}`` (either bound optional).
    KPIs without target metadata are excluded from the resulting dict.
    """
    result: dict[str, float] = {}
    for key in kpi_keys:
        target = targets.get(key)
        if not target:
            continue
        lo = target.get("min")
        hi = target.get("max")
        in_target = 0
        total = 0
        for entry in daily_entries:
            v = entry.get("kpis", {}).get(key)
            if v is None:
                continue
            total += 1
            if lo is not None and v < lo:
                continue
            if hi is not None and v > hi:
                continue
            in_target += 1
        if total == 0:
            continue
        result[key] = round(in_target / total, 4)
    return result


def fetch_month(
    report_month: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    aggregate: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Return one-month payload (backward-compatible flat dict).

    Calls :func:`fetch_month_with_provenance` and discards the data_source /
    notes tuple so existing callers and tests keep working unchanged.
    """
    data, _, _ = fetch_month_with_provenance(
        report_month, equipment_ids, kpi_keys, eq_type, aggregate, equipment_meta
    )
    return data


def fetch_month_with_provenance(
    report_month: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    aggregate: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> tuple[dict, str, list[str]]:
    """Provider-aware variant of :func:`fetch_month`.

    Fetches the full calendar month through the InS batch adapter
    (``fetch_daily_series_payload``) so the existing weekly bucketing +
    aggregation logic keeps owning the rich monthly shape (``weekly[]`` /
    ``aggregated`` / ``maintenance`` / ``critical_events``). A single
    batch call reuses one InS client/session across the full window.
    Any ``HttpProviderError`` propagates so the CLI surfaces the failure
    instead of masking it with synthetic output.
    """
    ins = _load_ins_provider()
    year, month = _parse_report_month(report_month)
    month_start, month_end, day_count = _month_bounds(year, month)
    week_buckets = _build_week_buckets(month_start, day_count)

    daily_entries = ins.fetch_daily_series_payload(
        start_date=month_start,
        day_count=day_count,
        equipment_ids=equipment_ids,
        kpi_keys=kpi_keys,
        eq_type=eq_type,
        equipment_meta=equipment_meta,
    )

    # Slice daily entries into week buckets and aggregate each.
    weekly: list[dict] = []
    union_alarms: list[dict] = []
    cursor = 0
    for bucket in week_buckets:
        bdays = bucket["day_count"]
        slice_entries = daily_entries[cursor : cursor + bdays]
        cursor += bdays
        agg = _aggregate_kpis(slice_entries, kpi_keys)
        bucket_alarms: list[dict] = []
        for entry in slice_entries:
            bucket_alarms.extend(entry.get("alarms") or [])
        union_alarms.extend(bucket_alarms)
        weekly.append(
            {
                "label": bucket["label"],
                "date_range": bucket["date_range"],
                "day_count": bdays,
                "kpis_mean": agg["kpis_mean"],
                "kpis_max": agg["kpis_max"],
                "kpis_min": agg["kpis_min"],
                "kpis_std": agg["kpis_std"],
                "alarms": bucket_alarms,
            }
        )

    aggregated = _weighted_aggregate_from_weekly(weekly, kpi_keys)
    aggregated["kpis_target_rate"] = _kpis_target_rate(daily_entries, kpi_keys, _default_targets())

    maintenance = _compute_maintenance(daily_entries, day_count)
    critical_events = [
        {
            "time": a.get("time", ""),
            "equipment_id": a.get("equipment_id", a.get("equipment", "")),
            "equipment": a.get("equipment", ""),
            "level": a.get("level", "critical"),
            "message": a.get("message", ""),
            "duration_minutes": None,
            "resolved": True,
        }
        for a in union_alarms
        if a.get("level") == "critical"
    ][:50]

    improvement_tracking: list[dict] = []

    # Sort alarms by time for deterministic output.
    union_alarms.sort(key=lambda a: a.get("time", ""))

    current: dict = {
        "weekly": weekly,
        "aggregated": aggregated,
        "maintenance": maintenance,
        "alarms": union_alarms,
        "critical_events": critical_events,
        "improvement_tracking": improvement_tracking,
    }
    if aggregate:
        # Aggregate mode drops bucket-level alarm streams to save bytes, but
        # keeps the unioned ``alarms`` for downstream TopN / critical-events use.
        for bucket in weekly:
            bucket.pop("alarms", None)
    # Preserve the canonical kpi_units map so monthly_kpi can render units
    # without re-scanning daily list.
    current["kpi_units"] = daily_entries[0].get("kpi_units", {}) if daily_entries else {}

    # Batch fetch always comes from the InS provider.
    return current, "ins", []


def _resolve_equipment_by_scope(eq_type: str, scope: str, scope_filter: str) -> list[dict]:
    list_eq = _load_list_equipment()
    if list_eq is None:
        return []
    result = list_eq.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])


def _parse_compare_csv(value: str | None) -> list[str]:
    if not value:
        return ["none"]
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        return ["none"]
    invalid = [p for p in parts if p not in VALID_COMPARES]
    if invalid:
        raise ValueError(f"--compare contains invalid basis: {','.join(invalid)}")
    # ``none`` is exclusive: tolerate it being mixed but normalize to a single
    # ``none`` so downstream paths don't double-handle it.
    if "none" in parts and len(parts) > 1:
        raise ValueError("--compare: 'none' must be the only basis when present")
    # Dedupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def build_result(
    report_month: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    compare_bases: list[str],
    eq_type: str = "all",
    aggregate: bool = False,
    is_scope_mode: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Build the full payload matching design doc §6.1."""
    year, month = _parse_report_month(report_month)
    month_start, month_end, day_count = _month_bounds(year, month)
    week_buckets = _build_week_buckets(month_start, day_count)

    auto_aggregate = aggregate or (is_scope_mode and len(equipment_ids) > 50)
    current, current_src, current_notes = fetch_month_with_provenance(
        report_month, equipment_ids, kpi_keys, eq_type, auto_aggregate, equipment_meta
    )

    # Resolve comparison periods and per-basis payloads.
    effective_bases = [b for b in compare_bases if b != "none"]
    compare_periods: dict[str, dict] = {}
    compare_block: dict[str, dict | None] = {}
    compare_warnings: list[str] = []
    compare_sources: dict[str, str] = {}
    compare_notes_all: list[str] = []

    for basis in effective_bases:
        py, pm = _compare_month_bounds(year, month, basis)
        p_start, p_end, _p_day_count = _month_bounds(py, pm)
        compare_periods[basis] = {"start": p_start, "end": p_end}
        if basis == "previous_year_month" and not _has_previous_year_data(year, month):
            compare_block[basis] = None
            compare_warnings.append("去年同期数据不可用，已跳过同比")
            continue
        prev_payload, prev_src, prev_notes = fetch_month_with_provenance(
            f"{py:04d}-{pm:02d}",
            equipment_ids,
            kpi_keys,
            eq_type,
            auto_aggregate,
            equipment_meta,
        )
        compare_sources[basis] = prev_src
        for note in prev_notes:
            tagged = f"[compare:{basis}] {note}"
            if tagged not in compare_notes_all:
                compare_notes_all.append(tagged)
        # compare blocks strip the per-bucket alarm streams + critical_events +
        # improvement_tracking to keep the JSON small — only mean / maintenance
        # baseline is what monthly_kpi.py actually consumes for delta math.
        compare_block[basis] = {
            "weekly": [],
            "aggregated": prev_payload.get("aggregated", {}),
            "maintenance": prev_payload.get("maintenance", {}),
            "alarms": [],
        }

    notes: list[str] = list(current_notes) + compare_notes_all
    all_sources = {current_src, *compare_sources.values()}
    if len(all_sources) > 1:
        raise RuntimeError(
            f"unexpected data_source mismatch (current={current_src}, compare={compare_sources}); "
            "InS provider should always tag results as 'ins'"
        )
    data_source = current_src

    equipment_names: dict[str, str] = {}
    if equipment_meta:
        equipment_names = {eid: meta.get("name", eid) for eid, meta in equipment_meta.items() if meta}

    result: dict = {
        "report_period": {
            "report_month": report_month,
            "month_start": month_start,
            "month_end": month_end,
            "day_count": day_count,
            "week_buckets": week_buckets,
        },
        "equipment_ids": equipment_ids,
        "equipment_names": equipment_names,
        "kpi_keys": kpi_keys,
        "compare_types": effective_bases,
        "compare_periods": compare_periods,
        "current": current,
        "compare": compare_block,
        "data_source": data_source,
        "data_notes": notes,
        "compare_warning": "；".join(compare_warnings) if compare_warnings else None,
    }
    if is_scope_mode:
        result["equipment_type"] = eq_type
        result["equipment_count"] = len(equipment_ids)
    result["aggregate_mode"] = "aggregated" if auto_aggregate else "detail"
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
    over_length = [item for item in equipment_ids if len(item) > 64]
    if over_length:
        return "--equipment id(s) exceed 64 chars: " + ",".join(over_length)
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
    parser = argparse.ArgumentParser(description="Query monthly report data")
    parser.add_argument("--report-month", required=True, help="Report month YYYY-MM")
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
        default="previous_month",
        help="Comma-separated bases: previous_month / previous_year_month / none",
    )
    parser.add_argument("--type", default="all", help="Equipment type filter")
    parser.add_argument("--scope", default=None, help="Scope: all/area/specific")
    parser.add_argument("--scope-filter", default="", help="Area names or equipment IDs for scope")
    parser.add_argument("--aggregate", action="store_true", help="Force aggregate mode (drop bucket alarms)")
    parser.add_argument(
        "--include-daily",
        action="store_true",
        help="Reserved for V2 trend analysis; MVP keeps daily series internal only",
    )
    args = parser.parse_args()

    try:
        try:
            _parse_report_month(args.report_month)
        except ValueError as exc:
            return _error(str(exc))

        eq_type = getattr(args, "type")
        if eq_type not in VALID_TYPES:
            return _error(f"--type must be one of {sorted(VALID_TYPES)}, got: {eq_type}")

        try:
            compare_bases = _parse_compare_csv(args.compare)
        except ValueError as exc:
            return _error(str(exc))

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
        # Drop special KPIs (mtbf/mttr/target_rate) from the query layer — they
        # are derived in monthly_kpi.py from the maintenance + aggregated blocks.
        query_kpi_keys = [k for k in kpi_keys if k not in SPECIAL_KPIS]
        kpi_error = _validate_kpi_keys(query_kpi_keys)
        if kpi_error:
            return _error(kpi_error)

        result = build_result(
            report_month=args.report_month,
            equipment_ids=equipment_ids,
            kpi_keys=query_kpi_keys,
            compare_bases=compare_bases,
            eq_type=eq_type,
            aggregate=args.aggregate,
            is_scope_mode=is_scope_mode,
            equipment_meta=equipment_meta,
        )
        # Echo the user-requested kpi_keys (including special) so monthly_kpi
        # knows to derive mtbf/mttr/target_rate even though the query layer
        # didn't pull them from the daily series.
        result["kpi_keys"] = kpi_keys
        out_path = write_payload(result)
        print(
            json.dumps(
                {
                    "output": str(out_path),
                    "report_month": result["report_period"]["report_month"],
                    "month_start": result["report_period"]["month_start"],
                    "month_end": result["report_period"]["month_end"],
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
