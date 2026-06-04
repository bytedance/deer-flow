"""阈值配置 — monitoring-analysis Skill。

覆盖 10 个测点类别的 warning/critical 阈值。
支持三种阈值类型：
  - warning / critical: 上限阈值（超过则报警）
  - warning_lower / critical_lower: 下限阈值（低于则报警）
  - warning_upper + warning_lower: 双向限值（用于有正负值的量）
"""

from __future__ import annotations

from typing import Any

# ===== 阈值字典 =====

THRESHOLDS: dict[str, dict[str, dict[str, Any]]] = {
    # ── 振动类 (vib): 2K/8K ──────────────────────────────
    "vib": {
        "v_rms":          {"warning": 4.5,  "critical": 7.1,  "unit": "mm/s"},
        "a_peak":         {"warning": 30,   "critical": 50,   "unit": "m/s²"},
        "a_rms":          {"warning": 20,   "critical": 35,   "unit": "m/s²"},
        "pp":             {"warning": 15,   "critical": 25,   "unit": "μm"},
        "kurtosis_index": {"warning": 4.0,  "critical": 6.0,  "unit": "—"},
    },

    # ── 机组振动类 (vibc): 9K ──────────────────────────────
    "vibc": {
        "rms":         {"warning": 8.0,   "critical": 12.0,  "unit": "μm"},
        "pp_value":    {"warning": 25.0,  "critical": 40.0,  "unit": "μm"},
        "p_value":     {"warning": 15.0,  "critical": 25.0,  "unit": "μm"},
        "gap": {
            "warning_upper": 12, "warning_lower": -12,
            "critical_upper": 18, "critical_lower": -18,
            "unit": "V",
        },
        "one_freq_y":  {"warning": 15.0,  "critical": 25.0,  "unit": "μm"},
        "two_freq_y":  {"warning": 8.0,   "critical": 15.0,  "unit": "μm"},
        "half_freq":   {"warning": 5.0,   "critical": 10.0,  "unit": "μm"},
        "remain_freq": {"warning": 5.0,   "critical": 10.0,  "unit": "μm"},
    },

    # ── 过程量类 (process_6k): 6K 静设备/腐蚀 ──────────────
    "process_6k": {
        "corrosionRate": {"warning": 0.3,  "critical": 0.5,  "unit": "mm/a"},
        "thinningRate":  {"warning": 0.3,  "critical": 0.5,  "unit": "mm/a"},
        "thickness":     {"warning_lower": 6.0, "critical_lower": 4.0, "unit": "mm"},
        "temperature":   {"warning": 350,  "critical": 400,  "unit": "℃"},
        "voltage":       {"warning_upper": 2.5, "critical_upper": 3.0, "unit": "V"},
    },

    # ── 测厚类 (thickness): 6K ────────────────────────────
    "thickness": {
        "thickness":      {"warning_lower": 6.0, "critical_lower": 4.0, "unit": "mm"},
        "corrosion_rate": {"warning": 0.3,  "critical": 0.5,  "unit": "mm/a"},
        "thinning_rate":  {"warning": 0.3,  "critical": 0.5,  "unit": "mm/a"},
        "temperature":    {"warning": 350,  "critical": 400,  "unit": "℃"},
    },

    # ── 腐蚀探针类 (probe): 6K ───────────────────────────
    "probe": {
        "corrosion_rate": {"warning": 0.3,  "critical": 0.5,  "unit": "mm/a"},
        "corrosion_loss": {"warning": 0.5,  "critical": 1.0,  "unit": "—"},
        "temperature":    {"warning": 350,  "critical": 400,  "unit": "℃"},
    },

    # ── 泄漏类 (leak): 7K ───────────────────────────────
    "leak": {
        "leak_rate":  {"warning": 100, "critical": 500, "unit": "ppm"},
        "leak_level": {"warning": 2,   "critical": 4,   "unit": "级"},
    },

    # ── 键相类 (key): 8K/9K ─────────────────────────────
    "key": {
        "gap": {
            "warning_upper": 12, "warning_lower": -12,
            "critical_upper": 18, "critical_lower": -18,
            "unit": "V",
        },
    },

    # ── 转速类 (speed): 2K ──────────────────────────────
    "speed": {
        "rms": {"warning": None, "critical": None, "unit": "—"},
    },
}


def get_threshold(category: str, feature: str) -> dict[str, Any] | None:
    """获取指定类别和特征的阈值配置。"""
    cat_thresholds = THRESHOLDS.get(category, {})
    return cat_thresholds.get(feature)


def check_threshold(
    category: str,
    feature: str,
    value: float,
) -> tuple[str, float, str] | None:
    """检查值是否超阈值。

    Returns:
        (severity, threshold_value, unit) 或 None（正常）
    """
    th = get_threshold(category, feature)
    if th is None:
        return None
    unit = th.get("unit", "")

    # 上限检查
    critical = th.get("critical")
    warning = th.get("warning")
    if critical is not None and value > critical:
        return ("critical", critical, unit)
    if warning is not None and value > warning:
        return ("warning", warning, unit)

    # 上限（双向）检查
    critical_upper = th.get("critical_upper")
    warning_upper = th.get("warning_upper")
    if critical_upper is not None and value > critical_upper:
        return ("critical", critical_upper, unit)
    if warning_upper is not None and value > warning_upper:
        return ("warning", warning_upper, unit)

    # 下限检查
    critical_lower = th.get("critical_lower")
    warning_lower = th.get("warning_lower")
    if critical_lower is not None and value < critical_lower:
        return ("critical", critical_lower, unit)
    if warning_lower is not None and value < warning_lower:
        return ("warning", warning_lower, unit)

    return None
