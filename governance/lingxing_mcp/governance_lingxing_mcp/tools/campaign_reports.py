from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.tools.ad_aggregate import fetch_daily_reports

API_PATH = "/pb/openapi/newad/spCampaignReports"


def query_campaign_reports(
    client: LingXingClient,
    sid: int,
    start_date: str,
    end_date: str,
    campaign_id: float | None = None,
    show_detail: int = 0,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询SP广告活动报表（日期范围版）。覆盖指标 #7 CVR / #8 ACOS / #9 ROAS。

    API: POST /pb/openapi/newad/spCampaignReports（X-API-VERSION: 2）。
    领星原生仅支持单日 report_date，本工具内部按天循环并聚合（单次跨度 ≤31 天）：
    绝对值求和，acos/roas/cvr/ctr/cpc 由求和结果重算。

    ⚠️ 此接口不返回 budget（预算），预算请用 lx_campaign_list 获取后按
    campaign_id 关联合并，得到"预算+ACOS+ROAS+CVR"完整视图。

    广告数据小时级，TTL=1800（30 分钟）。
    """
    base_params = {
        "sid": sid,
        "show_detail": show_detail,
        "offset": offset,
        "length": length,
    }
    rows = fetch_daily_reports(
        client,
        API_PATH,
        base_params,
        start_date,
        end_date,
        key_fields=("campaign_id",),
        ttl_seconds=1800,
    )
    if campaign_id is not None and rows and "error" not in rows[0]:
        rows = [r for r in rows if r.get("campaign_id") == campaign_id]
    return rows
