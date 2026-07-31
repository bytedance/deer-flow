import json
import logging
import time

import httpx

from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.signing import sign_request

logger = logging.getLogger(__name__)


class LingXingClient:
    """领星 OpenAPI HTTP 客户端：签名 + 鉴权 + 按键 TTL 缓存。

    缓存语义：每个 cache_key 独立记录过期时间 (now + ttl_seconds)。
    ttl_seconds <= 0 表示不缓存（每次都发真实请求）。
    """

    def __init__(self, config: LXConfig, auth: LingXingAuth | None = None):
        self._config = config
        self._auth = auth or LingXingAuth(config)
        # cache_key -> (result, expires_at_epoch_seconds)
        self._cache: dict[tuple, tuple[dict, float]] = {}

    def _cache_key(self, method: str, path: str, params: dict) -> tuple:
        # JSON-serialize params so list/dict values (e.g. sid=[1,2]) are hashable.
        return (method.upper(), path, json.dumps(params, sort_keys=True, default=str))

    def request(self, method: str, path: str, params: dict, ttl_seconds: int) -> dict:
        cache_key = self._cache_key(method, path, params)
        if ttl_seconds > 0:
            entry = self._cache.get(cache_key)
            if entry is not None and time.time() < entry[1]:
                return entry[0]

        # 构造签名参数（鉴权失败也返回统一 dict，避免异常逃逸到调用方）
        try:
            access_token = self._auth.get_access_token()
        except Exception as e:
            logger.warning("lingxing auth failed for %s %s: %s", method, path, e)
            return {"code": -1, "message": f"auth failed: {e}", "data": []}
        sign_params = dict(params)
        sign_params["access_token"] = access_token
        sign_params["app_key"] = self._config.app_id
        sign_params["timestamp"] = str(int(time.time()))
        # JSON-serialize list/dict values so signing (key=value) and URL encoding
        # stay consistent — otherwise httpx encodes sid=[1] as sid=1, mismatching
        # the signature computed from sid=[1, 2].
        # 必须用紧凑分隔符（无空格）：领星按 "[8074,8075]" 形式重建签名串，
        # Python 默认 json.dumps 产生 "[8074, 8075]"（带空格）会导致多元素
        # 数组签验失败（api sign not correct，2026-07-30 真实探测确认）。
        for k, v in list(sign_params.items()):
            if isinstance(v, (list, dict)):
                sign_params[k] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        sign = sign_request(sign_params, app_id=self._config.app_id)
        sign_params["sign"] = sign

        url = f"{self._config.api_base}{path}"
        try:
            # 领星 OpenAPI 传输约定（2026-07-30 全端点真实探测确认）：
            # - GET：所有参数（业务+鉴权）走 URL query params。
            # - POST：业务参数走 JSON body（保持原始类型），鉴权参数
            #   （access_token/app_key/timestamp/sign）走 query params；
            #   签名仍覆盖全部业务参数（list/dict 取 JSON 序列化值）。
            #   query 方式调 POST 会被领星返回"查询异常/参数有误"。
            # 429（频率限制）按指数退避重试，最多 3 次。
            max_attempts = 3
            for attempt in range(max_attempts):
                if method.upper() == "GET":
                    r = httpx.get(url, params=sign_params, timeout=30)
                else:
                    auth_keys = {"access_token", "app_key", "timestamp", "sign"}
                    query_params = {k: v for k, v in sign_params.items() if k in auth_keys}
                    r = httpx.post(url, params=query_params, json=params, timeout=30)
                if r.status_code == 429 and attempt < max_attempts - 1:
                    backoff = 0.5 * (2**attempt)
                    logger.warning("lingxing API %s %s rate limited (429), retry in %.1fs", method, path, backoff)
                    time.sleep(backoff)
                    continue
                break
            if r.status_code == 429:
                return {"code": 429, "message": "rate limited after 3 retries", "data": []}
            result = r.json()
        except Exception as e:
            logger.warning("lingxing API %s %s failed: %s", method, path, e)
            return {"code": -1, "message": str(e), "data": []}

        if ttl_seconds > 0:
            self._cache[cache_key] = (result, time.time() + ttl_seconds)

        return result
