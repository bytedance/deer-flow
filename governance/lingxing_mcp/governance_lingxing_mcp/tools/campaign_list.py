from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/pb/openapi/newad/spCampaigns"


def query_campaign_list(
    client: LingXingClient,
    sid: int,
    state: str | None = None,
    offset: int = 0,
    length: int = 15,
    next_token: str | None = None,
) -> list[dict]:
    """查询SP广告活动列表（管理数据），包含每日预算。覆盖指标 #10 广告活动-预算。

    API: POST /pb/openapi/newad/spCampaigns。
    返回 campaign_id / name / campaign_type / targeting_type / state /
    daily_budget / bidding / start_date / end_date / portfolio_id / tags。

    闭环：与 lx_campaign_reports 通过 campaign_id 关联——先调本工具获取
    活动列表+预算，再调 lx_campaign_reports 获取效果数据，合并完整视图。

    预算可能调整，TTL=3600（1 小时）。
    """
    params = {"sid": sid, "offset": offset, "length": length}
    if state is not None:
        params["state"] = state
    if next_token is not None:
        params["next_token"] = next_token
    result = client.request("POST", API_PATH, params=params, ttl_seconds=3600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "campaign list failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        return data.get("list") or data.get("data") or []
    return data or []
