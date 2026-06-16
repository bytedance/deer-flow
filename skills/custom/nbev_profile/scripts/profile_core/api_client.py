"""
api_client.py — 画像查询接口客户端

接口形态：POST {API_BASE}/{tableName}/query
body: {requestId, sqlid, queryValues:[branch_code, [month]]}
响应: {code, message, data, executionTime}，code==200 为成功。
负责：超时、指数退避重试、按业务 code 判错、requests 优雅降级、结构化日志。
"""

from __future__ import annotations

import time

from . import config
from .errors import ApiError
from .obs import log

try:
    import requests
    _REQUESTS_OK = True
except ImportError:  # pragma: no cover
    requests = None  # type: ignore
    _REQUESTS_OK = False


def query_dimension(dimension: str, *, request_id: str, org_id: str, month: str) -> list[dict]:
    """查询某维度画像，返回 data 列表（行字典）。失败抛 ApiError。"""
    if not _REQUESTS_OK:
        raise ApiError(
            "DEPENDENCY_MISSING", "运行环境缺少 requests 依赖",
            hint="请在沙箱安装 requests（pip install requests）",
        )
    if dimension not in config.DIMENSION_QUERY:
        raise ApiError("UNKNOWN_DIMENSION", f"未知画像维度：{dimension}")
    spec = config.DIMENSION_QUERY[dimension]
    url = f"{config.API_BASE}/{spec['table_name']}/query"
    query_values = [org_id, [month], *spec.get("extra_values", [])]
    body = {"requestId": request_id, "sqlid": spec["sqlid"], "queryValues": query_values}

    last: ApiError | None = None
    for attempt in range(config.MAX_RETRY + 1):
        t0 = time.time()
        try:
            resp = requests.post(url, json=body, timeout=config.API_TIMEOUT)
            cost = round((time.time() - t0) * 1000)
            if resp.status_code >= 500:
                last = ApiError("UPSTREAM_5XX", f"HTTP {resp.status_code}", retryable=True)
                log("api_5xx", level="WARNING", request_id=request_id,
                    dimension=dimension, status=resp.status_code, attempt=attempt, cost_ms=cost)
            elif resp.status_code != 200:
                log("api_http_error", level="ERROR", request_id=request_id,
                    dimension=dimension, status=resp.status_code)
                raise ApiError("UPSTREAM_HTTP_ERROR", f"HTTP {resp.status_code}",
                               hint="请检查查询参数")
            else:
                payload = resp.json() or {}
                code = payload.get("code")
                if code == 200:
                    rows = payload.get("data") or []
                    log("api_ok", request_id=request_id, dimension=dimension,
                        attempt=attempt, cost_ms=cost, rows=len(rows))
                    return rows
                retryable = code in config.RETRYABLE_API_CODES
                log("api_biz_error", level="WARNING" if retryable else "ERROR",
                    request_id=request_id, dimension=dimension, biz_code=code)
                err = ApiError(
                    f"PROFILE_API_{code}",
                    f"画像查询失败（{code}）：{payload.get('message','')}",
                    hint="请稍后重试" if retryable else "请联系管理员核对该维度SQL配置",
                    retryable=retryable,
                )
                if not retryable:
                    raise err
                last = err
        except requests.Timeout:
            last = ApiError("API_TIMEOUT", "画像查询超时", retryable=True)
            log("api_timeout", level="WARNING", request_id=request_id,
                dimension=dimension, attempt=attempt)
        except requests.RequestException as e:
            last = ApiError("API_CONN_ERROR", f"画像查询连接失败：{e}", retryable=True)
            log("api_conn_error", level="WARNING", request_id=request_id,
                dimension=dimension, attempt=attempt, err=str(e))

        if attempt < config.MAX_RETRY:
            time.sleep(min(2 ** attempt, 4))

    assert last is not None
    last.hint = last.hint or "画像服务暂时不可用，请稍后重试"
    log("api_give_up", level="ERROR", request_id=request_id,
        dimension=dimension, error_code=last.code)
    raise last
