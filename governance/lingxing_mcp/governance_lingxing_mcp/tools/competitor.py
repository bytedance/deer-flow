from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/basicOpen/tool/competitiveMonitor/list"


def query_competitor_monitor(
    client: LingXingClient,
    search_field: str | None = None,
    search_value: str | None = None,
    levels: list | None = None,
    update_time_start: str | None = None,
    update_time_end: str | None = None,
    offset: int = 0,
    length: int = 20,
) -> list[dict]:
    """查询竞品监控数据。覆盖指标 #16 竞品-排名 / #17 竞品-价格。

    API: POST /basicOpen/tool/competitiveMonitor/list。
    返回 asin/title/big_category_rank(大类BSR)/small_ranks(小类排名)/
    price/buybox_price/avg_price/star/review_num/fba_seller_num/monitor_status。
    search_value 为 ASIN（多个逗号分隔，上限 200）。levels: 1=A,2=B,3=C,4=D。

    ⚠️ 限制：竞品为监控制，且领星无添加竞品API——竞品需先在领星ERP网页端
    （工具→竞品监控）添加；查询为空时应提示用户。API 不直接返回销量字段
    （#15 竞品-销量可通过 BSR 排名变化趋势间接推断）。

    T+1 数据，TTL=21600（6 小时）。
    """
    params = {"offset": offset, "length": length}
    if search_field is not None:
        params["search_field"] = search_field
    if search_value is not None:
        params["search_value"] = search_value
    if levels is not None:
        params["levels"] = levels
    if update_time_start is not None:
        params["update_time_start"] = update_time_start
    if update_time_end is not None:
        params["update_time_end"] = update_time_end
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "competitor monitor failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        rows = data.get("list") or data.get("data") or []
    else:
        rows = data or []
    if not rows:
        return [
            {
                "info": "no monitored competitors found",
                "hint": "竞品为监控制：请先在领星ERP网页端（工具→竞品监控）添加竞品ASIN后再查询",
            }
        ]
    return rows
