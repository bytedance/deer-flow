"""Shared constants, utilities, and helpers for monthly report scripts.

This module is a self-contained copy for the monthly-report skill.
It contains daily constants plus monthly-specific constants and functions.
No weekly-specific functions.
"""

from __future__ import annotations

import calendar
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
REPORT_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")

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
    "sms_abnormal_count": "条",
    "sms_abnormal_pending": "条",
}

# ---------------------------------------------------------------------------
# SMS abnormal severity mapping
# ---------------------------------------------------------------------------

SMS_SEVERITY_MAP: list[tuple[int, str]] = [
    (60, "critical"),
    (41, "high"),
    (21, "medium"),
    (0, "low"),
]

SMS_SEVERITY_DISPLAY: dict[str, str] = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
}

SMS_SEVERITY_RANK: dict[str, int] = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}

# ---------------------------------------------------------------------------
# KPI display names — daily + monthly
# ---------------------------------------------------------------------------

KPI_DISPLAY_NAMES: dict[str, str] = {
    "runtime_rate": "运行率",
    "downtime_count": "停机次数",
    "alarm_count": "告警数量",
    "output": "产量",
    "corrosion_rate": "腐蚀速率",
    "thickness_loss": "壁厚减薄量",
    "vibration_level": "振动水平",
    "bearing_temp": "温度",
    "flow_rate": "流量",
    "outlet_pressure": "出口压力",
    "valve_temp": "阀温",
    "vibration_velocity_rms": "振动速度有效值",
    "vibration_acceleration_peak": "振动加速度峰值",
    "kurtosis_index": "峭度指标",
}

KPI_DISPLAY_NAMES_MONTHLY: dict[str, str] = {
    **KPI_DISPLAY_NAMES,
    "mtbf": "MTBF",
    "mttr": "MTTR",
    "target_rate": "达标率",
    "sms_abnormal_count": "SMS异常数",
    "sms_abnormal_pending": "待处理异常",
}

# ---------------------------------------------------------------------------
# KPI direction
# ---------------------------------------------------------------------------

KPI_BETTER_WHEN_HIGHER: set[str] = {
    "runtime_rate", "output", "flow_rate", "outlet_pressure",
}

# ---------------------------------------------------------------------------
# Per-equipment-type default KPI keys (monthly includes mtbf/mttr/target_rate)
# ---------------------------------------------------------------------------

_EQUIPMENT_TYPE_DEFAULT_KPIS: dict[str, list[str]] = {
    "all": ["runtime_rate", "downtime_count", "alarm_count", "mtbf", "mttr", "target_rate"],
    "static_equipment": ["runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss", "mtbf", "mttr", "target_rate"],
    "rotating_machinery": ["runtime_rate", "vibration_level", "bearing_temp", "downtime_count", "mtbf", "mttr", "target_rate"],
    "pump": ["vibration_velocity_rms", "vibration_acceleration_peak", "bearing_temp", "kurtosis_index", "mtbf", "mttr", "target_rate"],
    "reciprocating_machinery": ["runtime_rate", "vibration_level", "valve_temp", "downtime_count", "alarm_count", "mtbf", "mttr", "target_rate"],
}


def get_kpi_catalog(eq_type: str) -> list[dict[str, str]]:
    """返回指定设备类型的 KPI 目录（含 key、name、unit），供 Round 1.5 表单生成使用。"""
    keys = _EQUIPMENT_TYPE_DEFAULT_KPIS.get(eq_type, _EQUIPMENT_TYPE_DEFAULT_KPIS["all"])
    return [
        {
            "key": key,
            "name": KPI_DISPLAY_NAMES_MONTHLY.get(key, key),
            "unit": KPI_UNITS.get(key, ""),
        }
        for key in keys
    ]

KPI_BETTER_WHEN_HIGHER_MONTHLY: set[str] = (
    KPI_BETTER_WHEN_HIGHER | {"mtbf", "target_rate"}
)

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


def validate_equipment_ids_length(equipment_ids: list[str]) -> str | None:
    """Extended validation with 64-char length check (monthly only)."""
    if not equipment_ids:
        return "--equipment must be a non-empty CSV"
    invalid = [item for item in equipment_ids if not EQUIPMENT_ID_PATTERN.fullmatch(item)]
    if invalid:
        return "--equipment contains invalid equipment id(s): " + ",".join(invalid)
    over_length = [item for item in equipment_ids if len(item) > 64]
    if over_length:
        return "--equipment id(s) exceed 64 chars: " + ",".join(over_length)
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


def detect_equipment_type(equipment_ids: list[str], *, resolved_type: str | None = None) -> str:
    """通过 Organize API 查询设备真实类型。

    若 ``resolved_type`` 已提供（由前端表单透传），直接返回，不再查组织树。
    """
    if resolved_type:
        return resolved_type
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


def resolve_equipment_by_scope(
    eq_type: str,
    scope: str,
    scope_filter: str,
    *,
    resolved_records: list[dict] | None = None,
) -> list[dict]:
    """按设备类型和范围解析设备列表。

    若 ``resolved_records`` 已提供（由前端表单透传），直接返回，不再查组织树。
    """
    if resolved_records is not None:
        return resolved_records
    list_eq = load_sibling_module("list_equipment")
    if list_eq is None:
        return []
    result = list_eq.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])


# ---------------------------------------------------------------------------
# KPI aggregation — monthly
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
# Date / month helpers — monthly-specific
# ---------------------------------------------------------------------------


def parse_report_month(value: str) -> tuple[int, int]:
    if not REPORT_MONTH_PATTERN.fullmatch(value):
        raise ValueError(f"invalid report month: {value} (expected YYYY-MM)")
    year, month = value.split("-")
    y, m = int(year), int(month)
    if not (2000 <= y <= 2100):
        raise ValueError(f"report month year out of range [2000, 2100]: {y}")
    if not (1 <= m <= 12):
        raise ValueError(f"report month month out of range [01, 12]: {m}")
    return y, m


def month_bounds(year: int, month: int) -> tuple[str, str, int]:
    """Return (month_start, month_end, day_count). Uses calendar.monthrange for leap-year safety."""
    _, day_count = calendar.monthrange(year, month)
    start = datetime(year, month, 1)
    end = datetime(year, month, day_count)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), day_count


def has_previous_year_data_monthly(year: int, month: int, boundary: str = "2024-01-01") -> bool:
    """Return True if previous-year month data should be available."""
    py, pm = year - 1, month
    return datetime(py, pm, 1) >= datetime.strptime(boundary, "%Y-%m-%d")
