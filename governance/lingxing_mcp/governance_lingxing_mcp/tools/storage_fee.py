from governance_lingxing_mcp.client import LingXingClient

MONTHLY_API_PATH = "/erp/sc/data/fba_report/storageFeeMonth"
LONG_TERM_API_PATH = "/erp/sc/data/fba_report/storageFeeLongTerm"


def query_storage_fee(
    client: LingXingClient,
    sid: int,
    fee_type: str,
    month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    offset: int = 0,
    length: int = 1000,
) -> list[dict]:
    """查询FBA仓储费（月仓储费 + 长期仓储费）。辅助指标 #23 库存冗余成本。

    fee_type=monthly（必填 month=yyyy-MM）:
        API POST /erp/sc/data/fba_report/storageFeeMonth
        返回 asin/fnsku/estimated_monthly_storage_fee/storage_rate/
        average_quantity_on_hand/item_volume/product_size_tier/month_of_charge/currency
    fee_type=long_term（必填 start_date/end_date）:
        API POST /erp/sc/data/fba_report/storageFeeLongTerm
        返回 asin/fnsku/6_mo_long_terms_storage_fee/12_mo_long_terms_storage_fee/
        qty_charged_*/snapshot_date/per_unit_volume/currency

    ⚠️ 接口无 ASIN 筛选参数，按 ASIN 分析时请拉取后按 asin 过滤。
    T+1 数据，TTL=21600（6 小时）。
    """
    if fee_type == "monthly":
        if not month:
            return [{"error": "month is required when fee_type=monthly (yyyy-MM)"}]
        path = MONTHLY_API_PATH
        params = {"sid": sid, "month": month, "offset": offset, "length": length}
    elif fee_type == "long_term":
        if not start_date or not end_date:
            return [{"error": "start_date and end_date are required when fee_type=long_term"}]
        path = LONG_TERM_API_PATH
        params = {
            "sid": sid,
            "start_date": start_date,
            "end_date": end_date,
            "offset": offset,
            "length": length,
        }
    else:
        return [{"error": f"invalid fee_type: {fee_type}, expected monthly or long_term"}]
    result = client.request("POST", path, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "storage fee failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        return data.get("list") or data.get("data") or []
    return data or []
