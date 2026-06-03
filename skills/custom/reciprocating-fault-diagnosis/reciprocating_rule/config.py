"""Reciprocating machine diagnosis – enumerations and constants.

Ported from the Java sg9k rule engine (HealthLevelEnum, AlarmEventCodeEnum,
ChannelTypeEnum, StateCodeEnum).
"""

from __future__ import annotations

# ── Health levels (HealthLevelEnum) ──────────────────────────────────────
HL_A       = 10   # Healthy
HL_B_MINUS = 19   # Normal, continuous operation OK
HL_B       = 20   # Normal, some indicators elevated
HL_B_PLUS  = 21   # Fault symptom present
HL_C_MINUS = 29   # Confirmed fault, low impact
HL_C       = 30   # Confirmed fault, long-term economic loss
HL_C_PLUS  = 31   # Confirmed fault, long-term safety risk
HL_D       = 40   # Severe fault

HL_NAMES: dict[int, str] = {
    HL_A: "A",
    HL_B_MINUS: "B-",
    HL_B: "B",
    HL_B_PLUS: "B+",
    HL_C_MINUS: "C-",
    HL_C: "C",
    HL_C_PLUS: "C+",
    HL_D: "D",
}

# ── Alarm levels (AlarmEventCodeEnum) ────────────────────────────────────
AL_NORMAL = 30
AL_ALERT  = 24
AL_DEF    = 23
AL_H      = 21
AL_HH     = 11

# ── Start / stop states (StateCodeEnum) ──────────────────────────────────
SS_UNKNOWN  = -1
SS_STOP     = 0
SS_NORMAL   = 1
SS_STARTING = 2
SS_STOPPING = 3
SS_SS       = 4

SS_NAMES: dict[int, str] = {
    SS_UNKNOWN: "UNKNOWN",
    SS_STOP: "STOP",
    SS_NORMAL: "NORMAL",
    SS_STARTING: "STARTING",
    SS_STOPPING: "STOPPING",
    SS_SS: "STARTSTOP",
}

# ── Position types (ChannelTypeEnum) → segment count ─────────────────────
POSITION_SEG_NUM: dict[str, int] = {
    "JSZD": 4,    # 机身振动
    "SZT":  36,   # 十字头振动
    "GTZD": 36,   # 缸头振动
    "PBY":  8,    # 活塞杆沉降Y
    "PBX":  8,    # 活塞杆偏摆X
    "KEY":  1,    # 键相
    "GCYL": 1,    # 盖侧压力
    "ZCYL": 1,    # 轴侧压力
}

# Position types that support segment alarm (with enabled segments)
SEG_ALARM_ENABLE: dict[str, list[str]] = {
    "SZT":  ["A0", "A17", "A18", "A35"],
    "GTZD": ["A0", "A17", "A18", "A35"],
    "PBY":  [f"A{i}" for i in range(8)],
    "PBX":  [f"A{i}" for i in range(8)],
    "JSZD": [f"A{i}" for i in range(4)],
}

# ── PBY → SZT segment mapping (for rod looseness diagnosis) ─────────────
PBY_SZT_SEG_MAP: dict[str, list[str]] = {
    "A0": ["A1", "A2", "A3", "A4"],
    "A1": ["A4", "A5", "A6", "A7", "A8"],
    "A2": ["A9", "A10", "A11", "A12", "A13"],
    "A3": ["A14", "A15", "A16"],
    "A4": ["A19", "A20", "A21", "A22"],
    "A5": ["A23", "A24", "A25", "A26", "A27"],
    "A6": ["A28", "A29", "A30", "A31"],
    "A7": ["A32", "A33", "A34"],
}

# ── Fault code → display name / recommendation ───────────────────────────
FAULT_INFO: dict[str, dict[str, str]] = {
    "CYLINDER_SCORING": {
        "name_init": "拉缸（初期）",
        "name_dev": "拉缸（发展）",
        "desc_init": "活塞杆跳动角域特征偏高，机身振动正常",
        "desc_dev": "活塞杆跳动异常",
        "recommend_init": "现场查看有无异响，气阀温度有无变化",
        "recommend_dev": "排查传感器故障、气阀故障、活塞磨损",
    },
    "PISTON_IMPACT_TDC": {
        "name_minor": "撞缸（盖侧/轻微）",
        "name_major": "撞缸（盖侧/严重）",
        "desc": "十字头振动角域 A0/A35 偏高",
        "recommend": "前往现场查看是否有异响",
    },
    "PISTON_IMPACT_BDC": {
        "name_minor": "撞缸（轴侧/轻微）",
        "name_major": "撞缸（轴侧/严重）",
        "desc": "十字头振动角域 A17/A18 偏高",
        "recommend": "前往现场查看是否有异响",
    },
    "ROD_LOOSENESS": {
        "name_warn": "活塞杆断裂/拉缸/连杆松动（预警）",
        "name_severe": "活塞杆断裂/拉缸/连杆松动（严重）",
        "desc_warn": "活塞杆跳动持续增长，且对应角域产生较大冲击",
        "desc_severe": "活塞杆跳动持续增长，对应角域产生较大冲击，且机组振动超标",
        "recommend_warn": "疑似发生活塞杆断裂/拉缸/连杆松动故障",
        "recommend_severe": "建议停机查看",
    },
    "CRANK_SHAFT_BREAK": {
        "name_b": "曲轴断裂（初期）",
        "name_c": "曲轴断裂（发展）",
        "name_d": "曲轴断裂（严重）",
        "desc_b": "多列同时出现气缸撞击趋势，疑似曲轴出现故障",
        "desc_c": "多列出现撞缸趋势，且机身振动也有增长趋势",
        "desc_d": "多列同时出现气缸冲击信号，且机身振动异常",
        "recommend_b": "密切关注",
        "recommend_c": "紧急处理",
        "recommend_d": "立即停车",
    },
    "VIB_ABNORMAL": {
        "name": "机组振动异常",
        "desc": "机身振动偏高",
        "recommend": "检查机组运行状态",
    },
}

# ── Feature list (160 features for typeList parameter) ───────────────────
BASE_FEATURES = [
    "one_freq_y", "one_freq_x", "two_freq_y", "two_freq_x",
    "three_freq_y", "three_freq_x", "avg", "half_freq",
    "p_value", "min", "pp_value", "remain_freq", "rms",
    "vol_max", "vol_min", "speed",
]

SEG_FEATURES = [
    f"seg_{i}_{feat}"
    for i in range(36)
    for feat in ["avg", "pp", "max", "rms"]
]

ALL_TYPE_LIST = BASE_FEATURES + SEG_FEATURES

# ── InS API constants ────────────────────────────────────────────────────
DEFAULT_CONFIG_PATH = "/ins-os-manage/configInfo/queryD901Config"
DEFAULT_DATA_PATH = "/ins-os-view/sg9kData/getTrendDataHis"
DATA_DENSITY = "high"
DATA_INCLUDE_FILTER = "history"
DATA_WINDOW_MS = 5 * 60 * 1000  # ±5 minutes
