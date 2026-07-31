from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.tools.ad_aggregate import fetch_daily_reports

API_PATH = "/pb/openapi/newad/spKeywordReports"


def query_sp_keyword_reports(
    client: LingXingClient,
    sid: int,
    start_date: str,
    end_date: str,
    show_detail: int = 0,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询SP广告关键词报表（日期范围版）。辅助指标 #11 关键词-广告位。

    API: POST /pb/openapi/newad/spKeywordReports（X-API-VERSION: 2）。
    领星原生仅支持单日 report_date，本工具内部按天循环并聚合（单次跨度 ≤31 天）。

    返回 keyword_id / keyword_text / match_type / campaign_id / campaign_name /
    ad_group_id / impressions / clicks / cost / orders / sales / units。

    广告数据小时级，TTL=1800（30 分钟）。
    """
    base_params = {
        "sid": sid,
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
        key_fields=("keyword_id",),
        ttl_seconds=1800,
    )
