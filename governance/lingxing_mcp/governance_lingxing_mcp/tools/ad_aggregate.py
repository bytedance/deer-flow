"""广告报表按天循环 + 聚合的共享逻辑。

领星广告报表原生仅支持单日 report_date；工具入参为日期范围（单次 ≤31 天），
服务端内部按天循环调用并聚合，对 Agent 透明：
- 绝对值（impressions/clicks/cost/orders/sales/units 等）直接求和
- 比率（acos/roas/cvr/ctr/cpc）由求和后的绝对值重新计算，不做简单平均
"""

import logging
from datetime import date, timedelta

from governance_lingxing_mcp.client import LingXingClient

logger = logging.getLogger(__name__)

MAX_SPAN_DAYS = 31

# 需要跨天求和的绝对值字段（存在的才加）
SUM_FIELDS = (
    "impressions",
    "clicks",
    "cost",
    "orders",
    "sales",
    "units",
    "same_orders",
    "same_sales",
    "orders_1d",
    "orders_7d",
    "orders_14d",
    "orders_30d",
    "sales_1d",
    "sales_7d",
    "sales_14d",
    "sales_30d",
)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _num(value) -> float | None:
    """领星数值字段可能是字符串（如 cost="12.34"），统一转 float；非数值返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def add_ratio_fields(row: dict) -> None:
    """由绝对值重算比率字段（就地修改）。"""
    cost = _num(row.get("cost")) or 0
    sales = _num(row.get("sales")) or 0
    clicks = _num(row.get("clicks")) or 0
    impressions = _num(row.get("impressions")) or 0
    orders = _num(row.get("orders")) or 0
    row["acos"] = _ratio(cost, sales)
    row["roas"] = _ratio(sales, cost)
    row["cvr"] = _ratio(orders, clicks)
    row["ctr"] = _ratio(clicks, impressions)
    row["cpc"] = _ratio(cost, clicks)


def fetch_daily_reports(
    client: LingXingClient,
    api_path: str,
    base_params: dict,
    start_date: str,
    end_date: str,
    key_fields: tuple[str, ...],
    ttl_seconds: int,
) -> list[dict]:
    """按天循环拉取广告报表并按 key_fields 聚合。

    返回聚合后的行列表；全部天数失败时返回 [{"error": ...}]。
    """
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start is None or end is None or start > end:
        return [{"error": f"invalid date range: {start_date} ~ {end_date}"}]
    if (end - start).days >= MAX_SPAN_DAYS:
        return [{"error": f"date span exceeds {MAX_SPAN_DAYS} days: {start_date} ~ {end_date}"}]

    merged: dict[tuple, dict] = {}
    failed_days: list[str] = []
    days = list(iter_days(start, end))
    for day in days:
        params = dict(base_params)
        params["report_date"] = day
        result = client.request("POST", api_path, params=params, ttl_seconds=ttl_seconds)
        if result.get("code") != 0:
            logger.warning("daily ad report %s %s failed: %s", api_path, day, result.get("message"))
            failed_days.append(day)
            continue
        rows = result.get("data")
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("data") or []
        for row in rows or []:
            key = tuple(row.get(f) for f in key_fields)
            bucket = merged.get(key)
            if bucket is None:
                bucket = {k: v for k, v in row.items() if k != "report_date"}
                merged[key] = bucket
                # 初始化时把非求和字段外的数值先清零，后面统一累加
                for field in SUM_FIELDS:
                    if field in bucket:
                        bucket[field] = 0
            for field in SUM_FIELDS:
                value = _num(row.get(field))
                if field in row and value is not None:
                    bucket[field] = round((_num(bucket.get(field)) or 0) + value, 4)

    if failed_days and not merged:
        return [{"error": f"all {len(days)} daily requests failed, first failure: {failed_days[0]}"}]
    if failed_days:
        logger.warning("partial daily failures (%d/%d): %s", len(failed_days), len(days), failed_days)

    out = list(merged.values())
    for row in out:
        add_ratio_fields(row)
    return out
