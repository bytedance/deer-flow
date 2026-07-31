from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/bd/profit/report/open/report/asin/list"


def query_profit_report_asin(
    client: LingXingClient,
    sids: list[int] | str | int,
    start_date: str,
    end_date: str,
    search_field: str | None = None,
    search_value: list | None = None,
    mids: list | None = None,
    monthly_query: bool | None = None,
    currency_code: str | None = None,
    order_status: str | None = None,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询ASIN维度利润报表，含详细收入/成本/费用/利润。覆盖指标 #22 配送费。

    API: POST /bd/profit/report/open/report/asin/list。日期跨度 ≤ 31 天。
    sids 支持数组/int/字符串（自动规范化为数组）。
    返回 asin / parentAsin / sellerSku / totalSalesQuantity / totalSalesAmount /
    totalAdsCost / fbaDeliveryFee(FBA配送费) / totalStorageFee / sellingFeeRefunds /
    totalSalesRefunds / reimbursements / grossProfit / grossMargin 等。

    order_status: Disbursed/Deferred/All。monthly_query=True 按月汇总（默认按天）。
    T+1 数据，TTL=21600（6 小时）。
    """
    if isinstance(sids, int):
        sids = [sids]
    elif isinstance(sids, str):
        # 官方单店铺字符串形式 "5608" → 单元素数组（与 asinList 探测结论一致）
        sids = [int(sids)] if sids.isdigit() else [sids]
    params = {
        "sids": sids,
        "startDate": start_date,
        "endDate": end_date,
        "offset": offset,
        "length": length,
    }
    if search_field is not None:
        params["searchField"] = search_field
    if search_value is not None:
        params["searchValue"] = search_value
    if mids is not None:
        params["mids"] = mids
    if monthly_query is not None:
        params["monthlyQuery"] = monthly_query
    if currency_code is not None:
        params["currencyCode"] = currency_code
    if order_status is not None:
        params["orderStatus"] = order_status
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "profit report failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        return data.get("list") or data.get("data") or []
    return data or []
