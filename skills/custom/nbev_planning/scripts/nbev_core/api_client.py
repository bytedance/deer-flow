"""
api_client.py — 三个达成测算接口的统一客户端

三接口同构（共享 AchievementCalculationRequest + 同前缀路径），故用一个 client 收敛。
负责：超时、指数退避重试、把网络异常翻译成结构化 ApiError、结构化日志。
"""

from __future__ import annotations

import time

from . import config
from .errors import ApiError
from .obs import log

# requests 优雅降级：缺失时不在 import 阶段崩，而是在调用时给出可读错误
try:
    import requests
    _REQUESTS_OK = True
except ImportError:  # pragma: no cover
    requests = None  # type: ignore
    _REQUESTS_OK = False


def call_calculation(dimension: str, payload: dict) -> dict:
    """调用某维度达成测算接口，返回原始 JSON。失败抛 ApiError。"""
    if not _REQUESTS_OK:
        raise ApiError(
            "DEPENDENCY_MISSING", "运行环境缺少 requests 依赖",
            hint="请在沙箱安装 requests（pip install requests）",
        )
    if dimension not in config.ENDPOINTS:
        raise ApiError("UNKNOWN_DIMENSION", f"未知测算维度：{dimension}")
    url = config.API_BASE + config.ENDPOINTS[dimension]
    request_id = payload.get("request_id")

    last: ApiError | None = None
    for attempt in range(config.MAX_RETRY + 1):
        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=config.API_TIMEOUT)
            cost = round((time.time() - t0) * 1000)
            if resp.status_code >= 500:
                last = ApiError("UPSTREAM_5XX", f"接口返回 {resp.status_code}", retryable=True)
                log("api_5xx", level="WARNING", request_id=request_id,
                    dimension=dimension, status=resp.status_code, attempt=attempt, cost_ms=cost)
            elif resp.status_code != 200:
                log("api_http_error", level="ERROR", request_id=request_id,
                    dimension=dimension, status=resp.status_code, cost_ms=cost)
                raise ApiError(
                    "UPSTREAM_HTTP_ERROR",
                    f"接口返回非200状态码 {resp.status_code}",
                    hint="请检查请求参数后重试",
                )
            else:
                log("api_ok", request_id=request_id, dimension=dimension,
                    attempt=attempt, cost_ms=cost)
                return resp.json() or {}
        except requests.Timeout:
            last = ApiError("API_TIMEOUT", "测算接口超时", retryable=True)
            log("api_timeout", level="WARNING", request_id=request_id,
                dimension=dimension, attempt=attempt)
        except requests.RequestException as e:
            last = ApiError("API_CONN_ERROR", f"接口连接失败：{e}", retryable=True)
            log("api_conn_error", level="WARNING", request_id=request_id,
                dimension=dimension, attempt=attempt, err=str(e))

        if attempt < config.MAX_RETRY:
            time.sleep(min(2 ** attempt, 4))

    assert last is not None
    last.hint = last.hint or "测算服务暂时不可用，请稍后重试"
    log("api_give_up", level="ERROR", request_id=request_id,
        dimension=dimension, error_code=last.code)
    raise last
