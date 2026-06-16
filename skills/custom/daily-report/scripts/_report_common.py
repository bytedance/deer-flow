"""日报脚本共享常量、校验工具和辅助函数。

仅包含日报脚本所需的常量和函数。
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
# 正则模式
# ---------------------------------------------------------------------------

EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
KPI_KEY_PATTERN = re.compile(r"^[a-z_]+$")

# ---------------------------------------------------------------------------
# 领域常量
# ---------------------------------------------------------------------------

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}
# ---------------------------------------------------------------------------
# KPI 单位
# ---------------------------------------------------------------------------

KPI_UNITS: dict[str, str] = {
    "runtime_rate": "%",
    "downtime_count": "次",
    "alarm_count": "条",
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
    "sms_abnormal_count": "条",
    "sms_abnormal_pending": "条",
}

# ---------------------------------------------------------------------------
# KPI 中文名称
# ---------------------------------------------------------------------------

KPI_DISPLAY_NAMES: dict[str, str] = {
    "runtime_rate": "运行率",
    "downtime_count": "停机次数",
    "alarm_count": "告警数量",
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
    "sms_abnormal_count": "SMS异常数",
    "sms_abnormal_pending": "待处理异常",
}

# ---------------------------------------------------------------------------
# KPI 方向 — 值越大越好的指标
# ---------------------------------------------------------------------------

KPI_BETTER_WHEN_HIGHER: set[str] = {
    "runtime_rate", "flow_rate", "outlet_pressure",
}

# ---------------------------------------------------------------------------
# KPI 异常阈值 — (方向, 阈值)
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
# 每种设备类型的默认 KPI
# ---------------------------------------------------------------------------

_EQUIPMENT_TYPE_DEFAULT_KPIS: dict[str, list[str]] = {
    "all": ["runtime_rate", "downtime_count", "alarm_count"],
    "static_equipment": ["runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss"],
    "rotating_machinery": ["runtime_rate", "vibration_level", "bearing_temp", "downtime_count"],
    "pump": ["vibration_velocity_rms", "vibration_acceleration_peak", "bearing_temp", "kurtosis_index"],
    "reciprocating_machinery": ["runtime_rate", "vibration_level", "valve_temp", "downtime_count", "alarm_count"],
}

_ARGPARSE_DEFAULT_KPIS = ["runtime_rate", "downtime_count", "alarm_count"]


def get_kpi_catalog(eq_type: str) -> list[dict[str, str]]:
    """返回指定设备类型的 KPI 目录（含 key、name、unit），供 Round 2 表单生成使用。"""
    keys = _EQUIPMENT_TYPE_DEFAULT_KPIS.get(eq_type, _EQUIPMENT_TYPE_DEFAULT_KPIS["all"])
    return [
        {
            "key": key,
            "name": KPI_DISPLAY_NAMES.get(key, key),
            "unit": KPI_UNITS.get(key, ""),
        }
        for key in keys
    ]

# ---------------------------------------------------------------------------
# SMS 异常等级映射
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
# CSV / 校验工具
# ---------------------------------------------------------------------------


def parse_csv(value: str | None) -> list[str]:
    """将逗号分隔字符串解析为去空白后的列表。"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    """列表去重，保持原有顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def validate_equipment_ids(equipment_ids: list[str]) -> str | None:
    """校验设备 ID 列表格式，返回错误信息或 None。"""
    if not equipment_ids:
        return "--equipment must be a non-empty CSV"
    invalid = [item for item in equipment_ids if not EQUIPMENT_ID_PATTERN.fullmatch(item)]
    if invalid:
        return "--equipment contains invalid equipment id(s): " + ",".join(invalid)
    return None


def validate_kpi_keys(kpi_keys: list[str], kpi_units_map: dict[str, str] | None = None) -> str | None:
    """校验 KPI 键列表格式和可支持性，返回错误信息或 None。"""
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
    """以 JSON 格式输出错误信息到 stdout，返回 0。"""
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# 模块加载器
# ---------------------------------------------------------------------------


def load_sibling_module(name: str):
    """动态加载同级目录下的 Python 模块，已加载则直接返回。

    用于在脚本中按需加载其他脚本，避免循环导入。
    """
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
# 设备类型检测
# ---------------------------------------------------------------------------


def detect_equipment_type(equipment_ids: list[str], *, resolved_type: str | None = None) -> str:
    """通过 Organize API 查询设备真实类型，所有设备同类型时返回该类型。

    用于在 --type=all 时自动推导正确的逐类型 KPI 映射（如泵 → 2K）。
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
    """按设备类型和范围解析设备列表，返回设备记录列表。

    若 ``resolved_records`` 已提供（由前端表单透传），直接返回，不再查组织树。
    """
    if resolved_records is not None:
        return resolved_records
    list_eq = load_sibling_module("list_equipment")
    if list_eq is None:
        return []
    result = list_eq.query_equipment(eq_type, scope, scope_filter, limit=10000)
    return result.get("equipment", [])
