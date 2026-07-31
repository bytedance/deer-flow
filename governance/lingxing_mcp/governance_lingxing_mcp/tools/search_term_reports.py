from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.tools.ad_aggregate import fetch_daily_reports

API_PATH = "/pb/openapi/newad/queryWordReports"


def query_search_term_reports(
    client: LingXingClient,
    sid: int,
    target_type: str,
    start_date: str,
    end_date: str,
    show_detail: int = 0,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询SP广告搜索词报表（日期范围版）。覆盖指标 #13 关键词-流量占比。

    API: POST /pb/openapi/newad/queryWordReports（X-API-VERSION: 2）。
    领星原生仅支持单日 report_date，本工具内部按天循环并聚合（单次跨度 ≤31 天）。
    target_type: keyword 关键词 / target 商品投放（领星原生必填）。

    返回 query（用户搜索词）/ keyword_text（匹配的关键词）/ match_type /
    campaign_id / campaign_name / asin / impressions / clicks / cost / orders / sales。
    流量占比 = 某关键词 clicks / 全部搜索词总 clicks，由 Agent 计算。

    T+1 数据，TTL=21600（6 小时）。
    """
    base_params = {
        "sid": sid,
        "target_type": target_type,
        "show_detail": show_detail,
        "offset": offset,
        "length": length,
    }
    return fetch_daily_reports(
        client,
        API_PATH,
        base_params,
        start_date,
        end_date,
        key_fields=("query", "campaign_id", "ad_group_id", "keyword_id"),
        ttl_seconds=21600,
    )
