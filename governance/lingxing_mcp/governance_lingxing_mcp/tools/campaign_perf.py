from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/pb/openapi/newad/spCampaignReports"


def query_campaign_perf(
    client: LingXingClient,
    sid: int,
    report_date: str,
    profile_id: int | None = None,
    show_detail: int = 0,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询 SP 广告活动报表。返回 targeting_type/clicks/cost/sales/orders/units 等。

    API: POST /pb/openapi/newad/spCampaignReports （sid 与 profile_id 二选一）。
    广告数据小时级，TTL=1800（30 分钟）。
    """
    params = {
        "sid": sid,
        "report_date": report_date,
        "show_detail": show_detail,
        "offset": offset,
        "length": length,
    }
    if profile_id is not None:
        params["profile_id"] = profile_id
    result = client.request("POST", API_PATH, params=params, ttl_seconds=1800)
    if result.get("code") != 0:
        return []
    return result.get("data") or []
