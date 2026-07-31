from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/erp/sc/routing/fba/fbaStock/fbaList"

# 库龄分段字段及其下限天数（分段下限 > 阈值即计入冗余）
AGE_SEGMENTS = (
    ("inv_age_0_to_30_days", 0),
    ("inv_age_31_to_60_days", 31),
    ("inv_age_61_to_90_days", 61),
    ("inv_age_91_to_180_days", 91),
    ("inv_age_181_to_270_days", 181),
    ("inv_age_271_to_365_days", 271),
    ("inv_age_365_plus_days", 366),
)


def _num(value) -> float:
    """领星数值字段可能是字符串，统一转 float。"""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def add_redundancy_fields(row: dict, threshold_days: int = 90) -> None:
    """按库龄分段计算冗余数量与冗余成本（就地修改）。

    冗余数量 = 分段下限 > threshold_days 的库龄段库存量之和
    （阈值 90 → 91-180 + 181-270 + 271-365 + 365+）；
    冗余成本 = 冗余数量 × cost（单位库存成本）。
    """
    redundant_qty = sum(
        _num(row.get(field))
        for field, lower in AGE_SEGMENTS
        if lower > threshold_days
    )
    unit_cost = _num(row.get("cost"))
    row["redundant_threshold_days"] = threshold_days
    row["redundant_quantity"] = int(redundant_qty) if redundant_qty == int(redundant_qty) else redundant_qty
    row["redundant_cost"] = round(redundant_qty * unit_cost, 2)


def query_fba_inventory(
    client: LingXingClient,
    sid: str | int,
    search_field: str | None = None,
    search_value: str | None = None,
    redundant_threshold_days: int = 90,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询FBA库存列表，含库龄分布。覆盖指标 #23 库存冗余成本 / #24 库存冗余数量。

    API: POST /erp/sc/routing/fba/fbaStock/fbaList。
    返回 asin/msku/fnsku/sku/product_name/afn_fulfillable_quantity(FBA可售)/
    afn_unsellable_quantity/afn_inbound_shipped_quantity(在途)/inv_age_*_days
    (0-30/31-60/61-90/91-180/181-270/271-365/365+ 各库龄段库存量)/cost(单位成本)。

    每行附加计算字段：
    - redundant_quantity: 库龄 > redundant_threshold_days(默认90) 的分段库存量之和
    - redundant_cost: 冗余数量 × cost

    T+1 数据，TTL=3600（1 小时）。
    """
    params = {"sid": str(sid), "offset": offset, "length": length}
    if search_field is not None:
        params["search_field"] = search_field
    if search_value is not None:
        params["search_value"] = search_value
    result = client.request("POST", API_PATH, params=params, ttl_seconds=3600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "fba inventory failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        rows = data.get("list") or data.get("data") or []
    else:
        rows = data or []
    for row in rows:
        if isinstance(row, dict):
            add_redundancy_fields(row, redundant_threshold_days)
    return rows
