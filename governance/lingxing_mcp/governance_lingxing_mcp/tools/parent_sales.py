from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/bd/productPerformance/openApi/asinList"


def query_parent_sales(
    client: LingXingClient,
    sid: list | str,
    start_date: str,
    end_date: str,
    search_value: list | None = None,
    summary_field: str = "parent_asin",
    length: int = 100,
) -> list[dict]:
    """查询产品表现（父ASIN 级）。

    asinList 返回字段含：
    - 销量: volume / order_items / amount
    - 流量: sessions_total (Sessions-Total) / sessions (Browser) / sessions_mobile (Mobile)
    - 转化: cvr (CVR, 直接返回) / volume_cvr / ad_cvr
    - 环比: volume_chain_ratio / order_chain_ratio / amount_chain_ratio
    - B2B: b2b_volume / b2b_amount / b2b_order_items
    - 毛利: gross_profit (结算毛利润)
    - 退款: return_amount

    ⚠️ 达成率缺失：asinList 不返回 target（目标）字段，需"目标管理"分类 API，
    当前未接入。T+1 数据，TTL=21600（6 小时）。
    """
    params = {
        "offset": 0,
        "length": length,
        "sort_field": "volume",
        "sort_type": "desc",
        "sid": sid,
        "start_date": start_date,
        "end_date": end_date,
        "summary_field": summary_field,
    }
    if search_value:
        params["search_field"] = "parent_asin"
        params["search_value"] = search_value
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)  # 6h
    if result.get("code") != 0:
        return []
    return result.get("data") or []
