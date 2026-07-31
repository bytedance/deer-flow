from governance_lingxing_mcp.client import LingXingClient

API_PATH = "/basicOpen/tool/keywordRanking/add"


def add_keyword_monitor(
    client: LingXingClient,
    mid: int,
    keywords: list,
    asins: list,
    types: list,
    is_sponsors: list,
    postcodes: list | None = None,
) -> dict:
    """添加关键词排名监控（写操作/Beta）。指标 #11/#12 的前置闭环。

    API: POST /basicOpen/tool/keywordRanking/add。
    types: 1=PC端, 2=移动端。is_sponsors: 0=否, 1=是（是否监控广告位）。

    ⚠️ 重要限制：
    - 此API为隐藏文档接口（未官方公开发布），存在变动风险，标记 Beta
    - 新添加的监控从添加日开始采集，无历史数据；通常次日才可通过
      lx_keyword_rank 查到排名
    - 调用前应先调 lx_keyword_rank 查重，并向用户确认后再执行；
      失败时降级提示用户到领星ERP网页端（工具→关键词排名）手动添加

    写操作不缓存（TTL=0）。
    """
    params = {
        "mid": mid,
        "keywords": keywords,
        "asins": asins,
        "types": types,
        "is_sponsors": is_sponsors,
    }
    if postcodes is not None:
        params["postcodes"] = postcodes
    result = client.request("POST", API_PATH, params=params, ttl_seconds=0)
    if result.get("code") != 0:
        return {
            "success": False,
            "message": result.get("message") or result.get("msg") or "add keyword monitor failed",
        }
    return {"success": True, "message": result.get("message") or result.get("msg") or "ok"}
