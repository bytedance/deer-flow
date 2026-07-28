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
) -> list[dict]:
    """查询关键词排名监控列表。返回 key_word/rank/current_page_rank/sbv_page/asin 等。

    API: POST /erp/sc/routing/tool/toolKeywordRank/getKeywordList。

    Risk: 领星排名查询相关 API 文档历史上曾被注释/调整（如 keywordRankingAdd
    等接口）。当前 GetKeywordList 端点经文档确认可用并返回 rank 字段；若端点
    失效或鉴权失败，本工具返回 [{"warning": "..."}] 以便上层感知，不阻塞流程。
    T+1 数据，TTL=21600（6 小时）。
    """
    params = {"offset": offset, "length": length}
    if mid is not None:
        params["mid"] = mid
    if start_date is not None:
        params["start_date"] = start_date
    if end_date is not None:
        params["end_date"] = end_date
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        logger.warning(
            "keyword rank API not available, endpoint may have changed: %s",
            result.get("message"),
        )
        return [
            {"warning": "keyword rank API not available, endpoint may have changed"}
        ]
    return result.get("data") or []
