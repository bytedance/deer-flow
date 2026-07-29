from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/bd/productPerformance/openApi/asinList"


def query_parent_ad(
    client: LingXingClient,
    sid: list | str,
    start_date: str,
    end_date: str,
    search_value: list | None = None,
    summary_field: str = "parent_asin",
    length: int = 100,
) -> list[dict]:
    """查询广告指标（父ASIN 级，来源统计→产品表现 asinList）。

    返回 acos/roas/acoas/clicks/ctr/spend/ad_sales_amount/impressions 等。
    asinList 直接返回这些字段（非计算）。T+1 统计数据，TTL=21600（6 小时）。

    口径修正（2026-07-29）：原用 spProductAdReports（广告报表），业务口径要求
    来源"统计→产品表现→父ASIN→acos"，故改用 asinList（与 lx_parent_sales 同端点）。
    asinList 返回全部字段，本工具聚焦广告指标。
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
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return []
    return result.get("data") or []
