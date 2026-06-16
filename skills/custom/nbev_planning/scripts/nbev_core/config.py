"""
config.py — 集中配置（全部走环境变量，零业务字面量进代码）

把"会变的东西"集中到一处，是 harness engineering 让 skill 健壮的关键：
接口地址、超时、重试次数随环境变化，不应散落在各处或硬编码。
"""

from __future__ import annotations

import os


def _env_float(key: str, default: float) -> float:
    """安全解析 float 环境变量：非法值回退默认并告警，绝不让模块加载崩溃。"""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        import sys
        print(f"[config] 环境变量 {key}='{raw}' 非法，回退默认 {default}", file=sys.stderr)
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        import sys
        print(f"[config] 环境变量 {key}='{raw}' 非法，回退默认 {default}", file=sys.stderr)
        return default


# 后端达成测算接口基址（三个接口共享前缀）
# 新 IP:端口 = http://8.148.158.241:8001，路径前缀沿用 /api/v1/marketing-planning
API_BASE = os.getenv(
    "MARKETING_PLANNING_API_BASE",
    "http://8.148.158.241:8001/api/v1/marketing-planning",
).rstrip("/")

# 三个维度的接口末段
ENDPOINTS = {
    "product": "/get-product-card-data",
    "customer": "/get-customer-card-data",
    "team": "/get-team-card-data",
}

# HTTP 行为（安全解析，非法环境变量自动回退）
API_TIMEOUT = _env_float("MARKETING_PLANNING_TIMEOUT", 60.0)
MAX_RETRY = _env_int("MARKETING_PLANNING_MAX_RETRY", 2)

# 维度固定执行顺序（与业务测算心法一致：产品 -> 队伍 -> 客户）
DIMENSION_ORDER = ("product", "team", "customer")

# 维度中英文显示名
DIMENSION_CN = {"product": "产品", "team": "队伍", "customer": "客户"}

# 业务护栏阈值（可被环境覆盖，便于机构差异化）
SHOUZUAN_NBEV_RATIO_RANGE = (
    _env_float("GUARD_SHOUZUAN_LOW", 0.80),
    _env_float("GUARD_SHOUZUAN_HIGH", 0.90),
)
