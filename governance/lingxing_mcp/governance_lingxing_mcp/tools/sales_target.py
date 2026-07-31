from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/bd/goal/management/open/store/batchSelect"

# 目标管理系列接口成功码为 1（而非常规的 0）
SUCCESS_CODES = (0, 1)


def query_sales_target(
    client: LingXingClient,
    assess_year: str,
) -> list[dict]:
    """查询店铺销售额目标及达成情况（指标 #1 店铺销售额达成率）。

    API: POST /bd/goal/management/open/store/batchSelect。
    返回每个店铺 goalAmount1~12（月目标）/ realAmount1~12（月实际）/
    completeRateAmount1~12（月完成率）/ totalGoalAmount / totalRealAmount / totalCompleteRate。

    ⚠️ 仅支持店铺维度，无父ASIN维度目标；ASIN 级达成率需用户提供目标值后
    用 lx_product_performance 的 amount 自行计算。
    ⚠️ 该接口成功码为 code=1（非常规 0），已做特殊适配。
    T+1 数据，TTL=21600（6 小时）。
    """
    params = {"assessYear": assess_year}
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") not in SUCCESS_CODES:
        return [{"error": result.get("message") or result.get("msg") or "sales target failed"}]
    return result.get("data") or []
