from collections import defaultdict

from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/basicOpen/salesAnalysis/productPerformance/performanceTrendByHour"


def _date_part(r_date: str) -> str:
    """从小时段 r_date 提取日期部分（前 10 位 yyyy-MM-dd）。"""
    return (r_date or "")[:10]


def _num(value) -> float:
    """领星数值字段可能是字符串（如 amount="431.64"），统一转 float。"""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def aggregate_to_day(rows: list[dict]) -> list[dict]:
    """把 24 个小时段聚合为天：volume/order_items/amount 求和，
    price = amount/volume 重算，sales_rank 取当天最后一个非空值。"""
    by_date: dict[str, dict] = defaultdict(
        lambda: {"volume": 0, "order_items": 0, "amount": 0.0, "sales_rank": None}
    )
    for row in rows:
        day = _date_part(str(row.get("r_date", "")))
        if not day:
            continue
        bucket = by_date[day]
        bucket["volume"] += _num(row.get("volume"))
        bucket["order_items"] += _num(row.get("order_items"))
        bucket["amount"] += _num(row.get("amount"))
        if row.get("sales_rank") is not None:
            bucket["sales_rank"] = row["sales_rank"]
    out = []
    for day in sorted(by_date):
        b = by_date[day]
        volume = b["volume"]
        amount = round(b["amount"], 2)
        out.append(
            {
                "r_date": day,
                "volume": int(volume) if float(volume).is_integer() else volume,
                "order_items": int(b["order_items"]) if float(b["order_items"]).is_integer() else b["order_items"],
                "amount": amount,
                "price": round(amount / volume, 2) if volume else None,
                "sales_rank": b["sales_rank"],
            }
        )
    return out


def query_sales_trend(
    client: LingXingClient,
    sids: str,
    date_start: str,
    date_end: str,
    summary_field: str,
    summary_field_value: str,
    granularity: str = "day",
) -> dict:
    """查询ASIN销量趋势（时间序列，补充 lx_product_performance 的区间汇总值）。

    API: POST /basicOpen/salesAnalysis/productPerformance/performanceTrendByHour。
    原生按小时返回；granularity=day 时服务端把 24 个小时段聚合为天。

    闭环：lx_list_stores → sids → 本工具(sids + summary_field_value=ASIN)，
    一次调用拿整段日期走势，无需循环单日报表接口。

    返回 {"data": [{r_date, volume, order_items, amount, price, sales_rank}...],
          "total": 区间汇总}。T+1 数据，TTL=21600（6 小时）。
    """
    params = {
        "sids": sids,
        "date_start": date_start,
        "date_end": date_end,
        "summary_field": summary_field,
        "summary_field_value": summary_field_value,
    }
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return {"error": result.get("message") or result.get("msg") or "sales trend failed", "data": [], "total": {}}
    payload = result.get("data")
    if isinstance(payload, dict):
        rows = payload.get("list") or payload.get("data") or []
        total = payload.get("total") or result.get("total") or {}
    else:
        rows = payload or []
        total = result.get("total") or {}
    if granularity == "day":
        rows = aggregate_to_day(rows)
    return {"data": rows, "total": total}
