"""positionType → (series, category, waveform) 三级路由。

数据来源: 测点特征值波形清单.md (2026-06-04)
29 种 positionType 注册表，覆盖 2K/6K/7K/8K/9K 五个数据系列。
"""

from __future__ import annotations

# ===== 完整 positionType 注册表 (29 种) =====
# 每条: (series, category, has_waveform, default_features)
_POINT_TYPE_TABLE: dict[int, tuple[str, str, bool, list[str]]] = {
    # ── 振动类 (vib): 2K/8K ──────────────────────────────
    23:  ("2k", "vib", True, ["a_peak", "v_rms", "a_rms", "pp",
         "wave_index", "peak_index", "pulse_index", "kurtosis_index",
         "margin_index", "skewness_index", "speed"]),
    24:  ("2k", "vib", True, ["a_peak", "v_rms", "speed"]),  # 第三方振动: 仅 ACC/SPEED
    26:  ("2k", "vib", True, ["a_peak", "v_rms", "a_rms", "pp",
         "wave_index", "peak_index", "pulse_index", "kurtosis_index",
         "margin_index", "skewness_index", "speed"]),
    27:  ("2k", "vib", True, ["a_peak", "v_rms", "a_rms", "pp",
         "wave_index", "peak_index", "pulse_index", "kurtosis_index",
         "margin_index", "skewness_index", "speed"]),
    83:  ("8k", "vib", True, ["pp_value", "rms", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),

    # ── 机组振动类 (vibc): 9K ──────────────────────────────
    91:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    92:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    93:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    94:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    95:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    96:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),
    99:  ("9k", "vibc", True, ["rms", "pp_value", "p_value", "half_freq",
         "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y",
         "remain_freq", "optional_freq_one", "optional_freq_two", "speed", "gap"]),

    # ── 转速/键相类 (speed/key): 无波形 ───────────────────
    29:  ("2k", "speed", False, ["rms"]),
    81:  ("8k", "key", False, ["speed", "gap"]),
    97:  ("9k", "key", False, ["speed", "gap", "pid", "state_running", "unit"]),

    # ── 过程量类 (process): 无波形 ────────────────────────
    22:  ("2k", "process", False, ["value"]),
    25:  ("2k", "process", False, ["value"]),
    28:  ("2k", "process", False, ["value"]),
    61:  ("6k", "process_6k", False, ["value", "temperature", "corrosionRate",
         "thickness", "thinningRate", "voltage"]),
    82:  ("8k", "process", False, ["value"]),
    84:  ("8k", "process", False, ["value"]),
    98:  ("9k", "process", False, ["value"]),
    163: ("7k", "process", False, ["value"]),

    # ── 测厚类 (thickness): UT 波形 ──────────────────────
    62:  ("6k", "thickness", True, ["thickness", "corrosion_rate",
         "thinning_rate", "temperature", "time_of_flight"]),
    64:  ("6k", "thickness", True, ["thickness", "corrosion_rate",
         "thinning_rate", "temperature", "time_of_flight"]),

    # ── 腐蚀探针类 (probe): 无波形 ────────────────────────
    63:  ("6k", "probe", False, ["resi_ratio", "corrosion_loss",
         "corrosion_rate", "temperature"]),

    # ── 泄漏类 (leak): 7K 专用，无波形 ───────────────────
    161: ("7k", "leak", False, ["leak_rate", "leak_amount", "leak_level"]),
    162: ("7k", "leak", False, ["leak_rate", "leak_amount", "leak_level"]),

    # ── 磁通量 (flux): 无波形 ────────────────────────────
    30:  ("2k", "flux", False, []),
}

# ===== 波形类型映射 (按类别) =====
_WAVE_TYPES_BY_CATEGORY: dict[str, list[str]] = {
    "vib": ["ACC", "SPEED", "SHIFT", "ENVELOPE", "SPECTRUM"],
    "vibc": ["SHIFT", "SPECTRUM", "RUNOUT"],
    "thickness": ["UT"],
}

# type=24 (2k第三方振动) 仅支持 ACC/SPEED
_WAVE_TYPES_OVERRIDE: dict[int, list[str]] = {
    24: ["ACC", "SPEED"],
}


# ===== 公开 API =====

def _lookup(point_type: int) -> tuple[str, str, bool, list[str]]:
    """内部查询，返回 (series, category, has_waveform, default_features)。"""
    return _POINT_TYPE_TABLE.get(
        point_type, ("8k", "vib", False, [])
    )


def resolve_endpoint_series(point_type: int) -> str:
    """根据 positionType 确定 endpoint_series (2k/6k/7k/8k/9k)。"""
    return _lookup(point_type)[0]


def resolve_category(point_type: int) -> str:
    """返回测点类别 (vib/vibc/key/speed/process/process_6k/thickness/probe/leak/flux)。"""
    return _lookup(point_type)[1]


def supports_waveform(point_type: int) -> bool:
    """判断该 positionType 是否支持波形数据。"""
    return _lookup(point_type)[2]


def default_features(point_type: int) -> list[str]:
    """返回该 positionType 的默认特征值列表（用于 typeList 参数）。"""
    return _lookup(point_type)[3]


def get_wave_types(point_type: int) -> list[str]:
    """返回该测点类型支持的波形类型列表。"""
    if point_type in _WAVE_TYPES_OVERRIDE:
        return _WAVE_TYPES_OVERRIDE[point_type]
    category = resolve_category(point_type)
    return _WAVE_TYPES_BY_CATEGORY.get(category, [])


# ===== 趋势端点路由 =====

_TREND_PATH_BY_SERIES: dict[str, str] = {
    "2k": "ins-os-view/data/getTrendDataHis",
    "6k": "ins-os-view/sg6kData/getTrendDataHis",
    "7k": "ins-os-view/sg7kData/getTrendDataHis",  # TODO: 验证端点
    "8k": "ins-os-view/sg8kData/getTrendDataHis",
    "9k": "ins-os-view/sg9kData/getTrendDataHis",
}

_WAVE_PATH_BY_SERIES: dict[str, str] = {
    "2k": "ins-os-view/data/getMPWaveDataHisList",  # 机泵用多探头波形接口
    "6k": "ins-os-view/sg6kData/getWaveDataHis",
    "8k": "ins-os-view/sg8kData/getWaveDataHis",
    "9k": "ins-os-view/sg9kData/getWaveDataHis",
}


def trend_path(series: str) -> str:
    """返回该 series 的趋势数据 HTTP 路径。"""
    return _TREND_PATH_BY_SERIES.get(series, _TREND_PATH_BY_SERIES["8k"])


def wave_path(series: str) -> str:
    """返回该 series 的波形数据 HTTP 路径。"""
    return _WAVE_PATH_BY_SERIES.get(series, "")


def trend_density(series: str) -> str:
    """返回该 series 的趋势数据 density 参数。"""
    return "high" if series in ("7k", "8k", "9k") else "1"


def trend_include_filter(series: str) -> str:
    """返回该 series 的 includeFilter 参数。"""
    if series == "8k":
        return "history,startstop,blackbox,alarm"
    if series in ("7k", "9k"):
        return "history"
    return ""


# ===== 9K 角域特征值 =====

def nine_k_segment_features() -> list[str]:
    """生成 9K 角域统计特征值列表 (seg_0_avg ~ seg_35_avg 等)。"""
    features: list[str] = []
    for stat in ("avg", "max", "rms", "pp"):
        for seg in range(36):
            features.append(f"seg_{seg}_{stat}")
    return features


# ===== 9K/通用 API typeList 可选值 =====

NINE_K_API_TYPE_LIST: list[str] = [
    "p_value", "pp_value", "avg", "rms", "one_freq_y", "two_freq_y",
    "remain_freq", "vol_max", "vol_min", "speed", "value", "max", "min",
    "pp", "X1_amp", "X1_phase", "X2_amp", "X2_phase", "X3_amp",
    "X3_phase", "half_amp", "remain",
]
