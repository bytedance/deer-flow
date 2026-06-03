"""Shared constants, utilities, and helpers for weekly report scripts.

This module is a self-contained copy for the weekly-report skill.
It contains daily constants plus weekly-specific functions (aggregate_kpis, has_previous_year_data_weekly).
No monthly constants/functions.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
KPI_KEY_PATTERN = re.compile(r"^[a-z_]+$")

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}
# ---------------------------------------------------------------------------
# KPI display names
# ---------------------------------------------------------------------------

KPI_DISPLAY_NAMES: dict[str, str] = {
    "runtime_rate": "运行率",
    "downtime_count": "停机次数",
    "alarm_count": "告警数量",
    "output": "产量",
    "corrosion_rate": "腐蚀速率",
    "thickness_loss": "壁厚减薄量",
    "vibration_level": "振动水平",
    "bearing_temp": "轴承温度",
    "flow_rate": "流量",
    "outlet_pressure": "出口压力",
    "valve_temp": "阀温",
    "vibration_velocity_rms": "振动速度有效值",
    "vibration_acceleration_peak": "振动加速度峰值",
    "kurtosis_index": "峭度指标",
}

# ---------------------------------------------------------------------------
# KPI direction
# ---------------------------------------------------------------------------

KPI_BETTER_WHEN_HIGHER: set[str] = {
    "runtime_rate", "output", "flow_rate", "outlet_pressure",
}

# ---------------------------------------------------------------------------
# CSV / validation utilities
# ---------------------------------------------------------------------------


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def validate_equipment_ids(equipment_ids: list[str]) -> str | None:
    if not equipment_ids:
        return "--equipment must be a non-empty CSV"
    invalid = [item for item in equipment_ids if not EQUIPMENT_ID_PATTERN.fullmatch(item)]
    if invalid:
        return "--equipment contains invalid equipment id(s): " + ",".join(invalid)
    return None


def validate_kpi_keys(kpi_keys: list[str], kpi_units_map: dict[str, str] | None = None) -> str | None:
    if not kpi_keys:
        return "--kpis must include at least one KPI key"
    invalid_format = [item for item in kpi_keys if not KPI_KEY_PATTERN.fullmatch(item)]
    if invalid_format:
        return "--kpis contains invalid KPI key(s): " + ",".join(invalid_format)
    if kpi_units_map is not None:
        unsupported = [item for item in kpi_keys if item not in kpi_units_map]
        if unsupported:
            return "--kpis contains unsupported KPI key(s): " + ",".join(unsupported)
    return None


def error_output(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Math / direction helpers
# ---------------------------------------------------------------------------


def direction(delta: float | None, better_when_higher: bool) -> str:
    if delta is None:
        return "flat"
    if abs(delta) < 1e-9:
        return "flat"
    if better_when_higher:
        return "up" if delta > 0 else "down"
    return "down" if delta > 0 else "up"


def safe_pct(numerator: float, denominator: float | None) -> float | None:
    if denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)


# ---------------------------------------------------------------------------
# Equipment meta helpers
# ---------------------------------------------------------------------------


def load_sibling_module(name: str):
    module = sys.modules.get(name)
    if module is not None:
        return module
    script_dir = Path(__file__).resolve().parent
    module_path = script_dir / f"{name}.py"
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, str(module_path))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    return module


# ---------------------------------------------------------------------------
# Equipment type detection
# ---------------------------------------------------------------------------


def detect_equipment_type(equipment_ids: list[str]) -> str:
    if not equipment_ids:
        return "all"
    module = load_sibling_module("list_equipment")
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


def resolve_equipment_by_scope(eq_type: str, scope: str, scope_filter: str) -> list[dict]:
    list_eq = load_sibling_module("list_equipment")
    if list_eq is None:
        return []
    result = list_eq.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])


# ---------------------------------------------------------------------------
# KPI aggregation — weekly-specific
# ---------------------------------------------------------------------------


def aggregate_kpis(daily_entries: list[dict], kpi_keys: list[str]) -> dict:
    """Compute mean/max/min/std across a list of {kpis: {...}} entries."""
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


# ---------------------------------------------------------------------------
# Date helper — weekly-specific
# ---------------------------------------------------------------------------


def has_previous_year_data_weekly(week_start: str, boundary: str = "2025-01-01") -> bool:
    """Return True if previous-year week data should be available."""
    prev_year_start = datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=365)
    return prev_year_start >= datetime.strptime(boundary, "%Y-%m-%d")
