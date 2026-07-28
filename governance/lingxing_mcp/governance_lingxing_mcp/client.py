import time
import logging
import httpx
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.signing import sign_request
from governance_lingxing_mcp.auth import LingXingAuth

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
        return (method.upper(), path, tuple(sorted(params.items())))

    def request(self, method: str, path: str, params: dict, ttl_seconds: int) -> dict:
        cache_key = self._cache_key(method, path, params)
        if ttl_seconds > 0:
            entry = self._cache.get(cache_key)
            if entry is not None and time.time() < entry[1]:
                return entry[0]

        # 构造签名参数
        access_token = self._auth.get_access_token()
        sign_params = dict(params)
        sign_params["access_token"] = access_token
        sign_params["app_key"] = self._config.app_id
        sign_params["timestamp"] = str(int(time.time()))
        sign = sign_request(sign_params, app_id=self._config.app_id)
        sign_params["sign"] = sign

        url = f"{self._config.api_base}{path}"
        try:
            if method.upper() == "GET":
                r = httpx.get(url, params=sign_params, timeout=30)
            else:
                r = httpx.post(url, data=sign_params, timeout=30)
            result = r.json()
        except Exception as e:
            logger.warning("lingxing API %s %s failed: %s", method, path, e)
            return {"code": -1, "message": str(e), "data": []}

        if ttl_seconds > 0:
            self._cache[cache_key] = (result, time.time() + ttl_seconds)

        return result
