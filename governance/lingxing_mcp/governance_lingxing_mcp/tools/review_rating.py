from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/basicOpen/openapi/service/v3/data/mws/reviews"


def query_review_rating(
    client: LingXingClient,
    date_field: str,
    start_date: str,
    end_date: str,
    sids: str | None = None,
    sort_field: str = "review_date",
    sort_type: str = "desc",
    search_field: str | None = None,
    search_value: str | None = None,
    status: str | None = None,
    star: str | None = None,
    offset: int = 0,
    length: int = 20,
) -> list[dict]:
    """查询Review明细列表（lx_review_list）。覆盖指标 #20 新增差评，辅助 #19 评分变化。

    API: POST /basicOpen/openapi/service/v3/data/mws/reviews。
    返回 review_id/asin/last_star(星级)/last_title/last_content(评论内容)/
    review_date/author/is_vp/images/videos/amazon_order_list(关联订单)/marketplace。
    date_field: review_time / create_time / last_update_time。
    star 支持逗号分隔多值，如 "1,2,3" 拉取低星差评。

    闭环：查询"昨天新增差评" → lx_list_stores 得 sids → 本工具
    (star="1,2,3", 起止日期=昨天, search_field="asin" 可选)。
    评论实时性强，TTL=0（不缓存，每次真实拉取）。
    """
    params = {
        "date_field": date_field,
        "start_date": start_date,
        "end_date": end_date,
        "sort_field": sort_field,
        "sort_type": sort_type,
        "offset": offset,
        "length": length,
    }
    if sids is not None:
        params["sids"] = sids
    if search_field is not None:
        params["search_field"] = search_field
    if search_value is not None:
        params["search_value"] = search_value
    if status is not None:
        params["status"] = status
    if star is not None:
        params["star"] = star
    result = client.request("POST", API_PATH, params=params, ttl_seconds=0)
    if result.get("code") != 0:
        return []
    return result.get("data") or []
