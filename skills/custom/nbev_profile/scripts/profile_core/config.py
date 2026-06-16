"""
config.py — 画像查询配置（全部走环境变量，零业务字面量散落）

画像接口是"通用查询"：POST /api/{tableName}/query，body 含 {requestId, sqlid, queryValues}。
三个维度各对应一组固定的 (tableName, sqlid)，集中在此处维护。
queryValues 统一为 [branch_code, [month]]，其中 branch_code == org_id。
"""

from __future__ import annotations

import os


def _env_float(key: str, default: float) -> float:
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


# 画像查询服务基址
API_BASE = os.getenv(
    "PROFILE_QUERY_API_BASE",
    "http://8.148.158.241:8000/api",
).rstrip("/")

# 三维度 -> (tableName 路径段, sqlid)
# 来源：画像查询接口文档「调用示例」
DIMENSION_QUERY = {
    "team": {
        "table_name": "omniMktAgentDomainIndex",
        "sqlid": "omni_mkt_agent_doain_index_phasl_03",
        "extra_values": [],            # 队伍画像无额外过滤值
    },
    "customer": {
        "table_name": "omniMktAgentPlanStatistic",
        "sqlid": "omni_mkt_agent_plan_statistic_data_05",
        "extra_values": [],            # 客户画像（SQL 内已含 granularity_flag='ALL_CUST'）
    },
    "product": {
        "table_name": "omniMktAgentPlanProductActivity",
        "sqlid": "omni_mkt_agent_plan_product_activity_02",
        "extra_values": [],
    },
}

# HTTP 行为（安全解析，非法环境变量自动回退）
API_TIMEOUT = _env_float("PROFILE_QUERY_TIMEOUT", 30.0)
MAX_RETRY = _env_int("PROFILE_QUERY_MAX_RETRY", 2)

# 维度展示名 / 顺序
DIMENSION_CN = {"team": "队伍", "customer": "客户", "product": "产品"}
DIMENSION_ORDER = ("team", "customer", "product")

# 接口业务错误码 -> 是否可重试（来自接口文档错误码表）
RETRYABLE_API_CODES = {50001, 50002, 50099}
