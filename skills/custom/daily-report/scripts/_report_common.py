"""Shared constants, utilities, and helpers for daily report scripts.

This module is a self-contained copy for the daily-report skill.
It contains only constants and functions needed by daily report scripts.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys
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
DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]

# ---------------------------------------------------------------------------
# KPI units
# ---------------------------------------------------------------------------

KPI_UNITS: dict[str, str] = {
    "runtime_rate": "%",
    "downtime_count": "次",
    "alarm_count": "条",
    "output": "件",
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
    "mtbf": "小时",
    "mttr": "小时",
    "target_rate": "%",
}

# ---------------------------------------------------------------------------
# KPI display names — daily only (no monthly extensions)
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
# KPI direction — "higher is better" set
# ---------------------------------------------------------------------------

KPI_BETTER_WHEN_HIGHER: set[str] = {
    "runtime_rate", "output", "flow_rate", "outlet_pressure",
}

# ---------------------------------------------------------------------------
# KPI anomaly thresholds
# ---------------------------------------------------------------------------

KPI_THRESHOLDS: dict[str, tuple[str, float]] = {
    "runtime_rate": ("below", 0.85),
    "corrosion_rate": ("above", 0.3),
    "thickness_loss": ("above", 1.5),
    "vibration_level": ("above", 10.0),
    "bearing_temp": ("above", 75.0),
    "valve_temp": ("above", 100.0),
    "downtime_count": ("above", 5),
}

# ---------------------------------------------------------------------------
# Per-type default KPI keys
# ---------------------------------------------------------------------------

_EQUIPMENT_TYPE_DEFAULT_KPIS: dict[str, list[str]] = {
    "all": ["runtime_rate", "downtime_count", "alarm_count"],
    "static_equipment": ["runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss"],
    "rotating_machinery": ["runtime_rate", "vibration_level", "bearing_temp", "downtime_count"],
    "pump": ["vibration_velocity_rms", "vibration_acceleration_peak", "bearing_temp", "kurtosis_index"],
    "reciprocating_machinery": ["runtime_rate", "vibration_level", "valve_temp", "downtime_count", "alarm_count"],
}

_ARGPARSE_DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]

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


def build_equipment_meta_from_names(
    equipment_ids: list[str],
    equipment_names: list[str],
) -> dict[str, dict] | None:
    if not equipment_names:
        return None
    return {
        eid: {"id": eid, "name": (equipment_names[i] if i < len(equipment_names) else eid)}
        for i, eid in enumerate(equipment_ids)
    }


def build_equipment_names_from_meta(
    equipment_meta: dict[str, dict] | None,
) -> dict[str, str]:
    if not equipment_meta:
        return {}
    return {eid: meta.get("name", eid) for eid, meta in equipment_meta.items() if meta}


# ---------------------------------------------------------------------------
# Module loader
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


def load_sibling_module_required(name: str):
    module = load_sibling_module(name)
    if module is None:
        raise RuntimeError(f"required sibling module not found: {name}")
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
