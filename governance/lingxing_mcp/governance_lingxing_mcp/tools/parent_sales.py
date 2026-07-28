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
    """查询产品表现（父ASIN 级）。返回达成率/Sessions/CVR/Orders/销售额。"""
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
    return result.get("data", [])
