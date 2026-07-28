from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/pb/openapi/newad/queryWordReports"


def query_keyword_share(
    client: LingXingClient,
    sid: int,
    report_date: str,
    profile_id: int | None = None,
    target_type: str = "keyword",
    show_detail: int = 0,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询 SP 用户搜索词报表。返回 query/target_id/match_type/clicks/cost/sales 等。

    API: POST /pb/openapi/newad/queryWordReports （sid 与 profile_id 二选一）。
    target_type: keyword 关键词 / target 商品投放。T+1 数据，TTL=21600（6 小时）。
    """
    params = {
        "sid": sid,
        "report_date": report_date,
        "target_type": target_type,
        "show_detail": show_detail,
        "offset": offset,
        "length": length,
    }
    if profile_id is not None:
        params["profile_id"] = profile_id
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return []
    return result.get("data") or []
