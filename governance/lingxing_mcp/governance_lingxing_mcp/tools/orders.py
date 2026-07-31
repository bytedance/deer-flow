from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/erp/sc/data/mws/orders"


def query_orders(
    client: LingXingClient,
    sid: int,
    start_date: str,
    end_date: str,
    date_type: int | None = None,
    order_status: str | None = None,
    fulfillment_channel: int | None = None,
    offset: int = 0,
    length: int = 100,
) -> dict:
    """查询亚马逊订单列表，支持按时间/状态/配送方式筛选。

    API: POST /erp/sc/data/mws/orders。日期跨度 ≤ 1 年。
    date_type: 1=订购时间(站点) 2=修改时间(北京) 3=平台更新(UTC) 10=发货时间。
    order_status: Pending/Unshipped/PartiallyShipped/Shipped/Canceled。
    fulfillment_channel: 1=FBA(AFN) 2=FBM(MFN)。

    返回 {"total": 总条数, "data": [...]}，每行含 amazon_order_id / order_status /
    order_total_amount / purchase_date_local / is_return / refund_amount /
    item_list(asin/seller_sku/local_sku/quantity_ordered/item_price)。
    ⚠️ 接口无 ASIN 筛选参数，按 ASIN 分析时请拉取后按 item_list[].asin 过滤。

    T+1 数据，TTL=21600（6 小时）。
    """
    params = {
        "sid": sid,
        "start_date": start_date,
        "end_date": end_date,
        "offset": offset,
        "length": length,
    }
    if date_type is not None:
        params["date_type"] = date_type
    if order_status is not None:
        params["order_status"] = order_status
    if fulfillment_channel is not None:
        params["fulfillment_channel"] = fulfillment_channel
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return {"error": result.get("message") or result.get("msg") or "orders failed", "total": 0, "data": []}
    data = result.get("data")
    if isinstance(data, dict):
        return {"total": data.get("total", 0), "data": data.get("list") or data.get("data") or []}
    rows = data or []
    return {"total": result.get("total", len(rows)), "data": rows}
