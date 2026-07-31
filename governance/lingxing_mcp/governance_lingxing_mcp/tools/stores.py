from governance_lingxing_mcp.client import LingXingClient

SELLER_LISTS_API_PATH = "/erp/sc/data/seller/lists"
ALL_MARKETPLACE_API_PATH = "/erp/sc/data/seller/allMarketplace"


def query_stores(client: LingXingClient) -> list[dict]:
    """查询当前账号下所有亚马逊店铺列表。

    这是几乎所有工具的前置依赖：返回的 sid（店铺ID）是大部分 API 的必传参数，
    mid（站点/国家ID）是关键词工具的必传参数。

    API: GET /erp/sc/data/seller/lists。
    返回字段含 sid / mid / name / seller_id / account_name / region / country /
    marketplace_id / has_ads_setting / status(0=停止,1=正常,2=异常,3=欠费)。

    店铺列表极少变化，TTL=86400（24 小时）。
    """
    result = client.request("GET", SELLER_LISTS_API_PATH, params={}, ttl_seconds=86400)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "list stores failed"}]
    return result.get("data") or []


def query_marketplaces(client: LingXingClient) -> list[dict]:
    """查询所有亚马逊市场列表，辅助选择目标市场。

    API: GET /erp/sc/data/seller/allMarketplace。
    返回字段含 mid / name / country / region(NA/EU/FE) / marketplace_id / currency_code。

    市场列表几乎不变，TTL=604800（7 天）。
    """
    result = client.request("GET", ALL_MARKETPLACE_API_PATH, params={}, ttl_seconds=604800)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "list marketplaces failed"}]
    return result.get("data") or []
