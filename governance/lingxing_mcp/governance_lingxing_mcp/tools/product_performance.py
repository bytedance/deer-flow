from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/bd/productPerformance/openApi/asinList"


def query_product_performance(
    client: LingXingClient,
    sid: list[int] | str | int,
    start_date: str,
    end_date: str,
    summary_field: str = "asin",
    search_field: str | None = None,
    search_value: str | list | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
    currency_code: str | None = None,
    offset: int = 0,
    length: int = 100,
) -> dict:
    """查询产品表现数据（核心工具，一站式返回全维度指标）。

    API: POST /bd/productPerformance/openApi/asinList。
    覆盖指标 #1(部分)/#2 流量(sessions_total)/#3 CVR/#4 acos/#5 roas/#6 acoas/
    #19 评分(avg_star+prev_star)/#21 退货率(return_goods_rate)/#25 可售天数(available_days)。

    sid 与官方一致的三种形式（2026-07-30 真实探测）：多店铺数组 [5609,5608]
    （上限200）；单店铺字符串 "5608" / int 5608（自动包装为 [5608]）/ 单元素数组。
    返回 {"total": 总条数, "list": [...]}；list 每行含销量/流量/转化/广告/利润/
    排名/库存/评论/退货等全字段（随 summary_field 维度聚合）。
    起止日期间隔 ≤ 92 天。T+1 数据，TTL=21600（6 小时）。
    """
    if isinstance(sid, int):
        sid = [sid]
    params = {
        "offset": offset,
        "length": length,
        "sid": sid,
        "start_date": start_date,
        "end_date": end_date,
        "summary_field": summary_field,
    }
    if search_field is not None:
        params["search_field"] = search_field
    if search_value is not None:
        params["search_value"] = search_value
    if sort_field is not None:
        params["sort_field"] = sort_field
        params["sort_type"] = sort_order or "desc"
    if currency_code is not None:
        params["currency_code"] = currency_code
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return {"error": result.get("message") or result.get("msg") or "product performance failed", "total": 0, "list": []}
    data = result.get("data")
    # 领星返回 data 直接为列表，或 {"total": n, "list": [...]} 信封结构，统一为后者
    if isinstance(data, dict):
        return {"total": data.get("total", 0), "list": data.get("list") or []}
    rows = data or []
    return {"total": len(rows), "list": rows}
