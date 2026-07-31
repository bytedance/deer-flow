from governance_lingxing_mcp.client import LingXingClient

# 2026-07-30 真实探测：fbaWarehouseDetail 端点两种传输方式均报错（疑似失效），
# 库存数据改用 fbaList（含 afn_fulfillable_quantity / afn_inbound_shipped_quantity）。
FBA_STOCK_API_PATH = "/erp/sc/routing/fba/fbaStock/fbaList"
SALES_FORECAST_API_PATH = "/erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature"


def query_inventory_days(
    client: LingXingClient,
    sid: int,
    asin: str,
    sug_type: int = 3,
    mode: int | None = None,
) -> dict:
    """查询 FBA 库存 + 销量预测并合并，返回可售天数。

    合并两个端点：
    - FBA 库存: POST /erp/sc/routing/fba/fbaStock/fbaList （按 asin 检索）
    - 销量预测: POST /erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature （sid+asin）

    返回 {asin, in_stock, in_transit, daily_sales, available_days}：
    - in_stock: FBA 可售 (afn_fulfillable_quantity)
    - in_transit: 在途 (afn_inbound_shipped_quantity)
    - daily_sales: 销量预测最近一天的日销
    - available_days: in_stock / daily_sales（日销为 0 时为 None）

    sug_type: 1 建议采购量 / 2 建议本地仓发货量 / 3 建议海外仓发货量。
    TTL=3600（1 小时）。
    """
    stock_params = {
        "search_field": "asin",
        "search_value": asin,
        "sid": str(sid),
        "offset": 0,
        "length": 20,
    }
    stock_result = client.request(
        "POST", FBA_STOCK_API_PATH, params=stock_params, ttl_seconds=3600
    )

    in_stock = 0
    in_transit = 0
    if stock_result.get("code") == 0:
        stock_data = stock_result.get("data")
        # fbaList 返回信封结构 {"total": n, "list": [...]}
        if isinstance(stock_data, dict):
            stock_rows = stock_data.get("list") or []
        else:
            stock_rows = stock_data or []
        if stock_rows:
            row = stock_rows[0]
            in_stock = row.get("afn_fulfillable_quantity", 0) or 0
            in_transit = row.get("afn_inbound_shipped_quantity", 0) or 0

    sales_params = {"sid": sid, "asin": asin, "sug_type": sug_type}
    if mode is not None:
        sales_params["mode"] = mode
    sales_result = client.request(
        "POST", SALES_FORECAST_API_PATH, params=sales_params, ttl_seconds=3600
    )

    daily_sales = 0
    if sales_result.get("code") == 0:
        data = sales_result.get("data", {}) or {}
        day_list = data.get("list", {}) if isinstance(data, dict) else {}
        if day_list:
            latest_date = max(day_list.keys())
            entry = day_list.get(latest_date, [0, 0, 0])
            daily_sales = entry[1] if len(entry) > 1 else 0

    available_days = round(in_stock / daily_sales, 1) if daily_sales > 0 else None

    return {
        "asin": asin,
        "in_stock": in_stock,
        "in_transit": in_transit,
        "daily_sales": daily_sales,
        "available_days": available_days,
    }
