import logging

from governance_lingxing_mcp.client import LingXingClient

logger = logging.getLogger(__name__)

API_PATH = "/erp/sc/routing/tool/toolKeywordRank/getKeywordList"


def query_keyword_rank(
    client: LingXingClient,
    offset: int = 0,
    length: int = 20,
    mid: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search_field: str | None = None,
    search_value: str | None = None,
) -> list[dict]:
    """查询关键词排名监控列表。覆盖指标 #11 关键词-广告位 / #12 关键词-自然位。

    API: POST /erp/sc/routing/tool/toolKeywordRank/getKeywordList。
    返回 key_word/asin/parent_asin/rank(综合排名)/page/current_page_rank/
    is_sponsored(0=自然位,1=广告位)/sbv_page/type(1=PC,2=移动)/monitor_time。
    search_field: key_word / asin；mid 从 lx_list_stores 获取，不传查全部站点。

    ⚠️ 闭环说明：本工具仅返回"已在监控中"的关键词。查询为空 = 该词未加入监控，
    可经用户确认后调用 lx_add_keyword_monitor 添加（次日开始有数据）。
    T+1 数据，TTL=21600（6 小时）。
    """
    params = {"offset": offset, "length": length}
    if mid is not None:
        params["mid"] = mid
    if start_date is not None:
        params["start_date"] = start_date
    if end_date is not None:
        params["end_date"] = end_date
    if search_field is not None:
        params["search_field"] = search_field
    if search_value is not None:
        params["search_value"] = search_value
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        logger.warning(
            "keyword rank API not available, endpoint may have changed: %s",
            result.get("message"),
        )
        return [
            {"error": result.get("message") or "keyword rank API not available, endpoint may have changed"}
        ]
    data = result.get("data")
    if isinstance(data, dict):
        rows = data.get("list") or data.get("data") or []
    else:
        rows = data or []
    if not rows:
        return [
            {
                "info": "keyword not monitored or no rank data",
                "hint": "该关键词未加入监控（领星排名为监控制）。可调用 lx_add_keyword_monitor "
                "添加监控，次日开始有排名数据；已监控的词请检查 mid/日期范围。",
            }
        ]
    return rows
