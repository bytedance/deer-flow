from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/basicOpen/salesAnalysis/returnOrder/analysisLists"


def query_return_analysis(
    client: LingXingClient,
    start_date: str,
    end_date: str,
    asin_type: str,
    date_type: int,
    store_id: list | None = None,
    mids: list | None = None,
    search_field: str | None = None,
    search_value: list | None = None,
    sort_field: str | None = None,
    offset: int = 0,
    length: int = 100,
) -> list[dict]:
    """查询退货分析数据（含环比对比）。覆盖指标 #21 退货率。

    API: POST /basicOpen/salesAnalysis/returnOrder/analysisLists。日期跨度 ≤ 366 天。
    asin_type: asin/msku/parentAsin/sku/spu。date_type: 0=退货时间, 1=下单时间。

    返回 curReturnGoodsCount(当期退货量)/curReturnGoodsVolumeRatio(当期退货率)/
    curVolume(当期销量)/preReturnGoodsCount/preReturnGoodsVolumeRatio(上期)/
    returnGoodsCountRatio(退货量环比)/returnGoodsVolumeRatioDiff(退货率环比差异)/
    curReturnGoodsCountDistribution(FBA/FBM退货分布)。

    相比 lx_product_performance 的 return_goods_rate，本工具提供环比、
    FBA/FBM 分布、退货/下单时间口径切换等更细维度。
    T+1 数据，TTL=21600（6 小时）。
    """
    params = {
        "startDate": start_date,
        "endDate": end_date,
        "asinType": asin_type,
        "dateType": date_type,
        "offset": offset,
        "length": length,
    }
    if store_id is not None:
        params["storeId"] = store_id
    if mids is not None:
        params["mids"] = mids
    if search_field is not None:
        params["searchField"] = search_field
    if search_value is not None:
        params["searchValue"] = search_value
    if sort_field is not None:
        params["sortField"] = sort_field
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)
    if result.get("code") != 0:
        return [{"error": result.get("message") or result.get("msg") or "return analysis failed"}]
    data = result.get("data")
    if isinstance(data, dict):
        # 响应为 data.records 结构
        records = data.get("records")
        if records is not None:
            return records
        return data.get("list") or data.get("data") or []
    return data or []
