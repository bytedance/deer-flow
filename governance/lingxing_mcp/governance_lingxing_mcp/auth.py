import logging
import time

import httpx

from governance_lingxing_mcp.config import LXConfig

logger = logging.getLogger(__name__)

TOKEN_URL = "/api/auth-server/oauth/access-token"
REFRESH_URL = "/api/auth-server/oauth/refresh-token"


class LingXingAuth:
    def __init__(self, config: LXConfig):
        self._config = config
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0

    def _fetch_token(self) -> None:
        r = httpx.post(
            f"{self._config.api_base}{TOKEN_URL}",
            data={"appId": self._config.app_id, "appSecret": self._config.app_secret},
            timeout=15,
        )
        data = r.json()
        if data.get("code") != "200":
            raise RuntimeError(f"token fetch failed: {data}")
        token_data = data["data"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._expires_at = time.time() + int(token_data.get("expires_in", 7199))

    def _refresh(self) -> None:
        if not self._refresh_token:
            self._fetch_token()
            return
        r = httpx.post(
            f"{self._config.api_base}{REFRESH_URL}",
            data={"refresh_token": self._refresh_token},
            timeout=15,
        )
        data = r.json()
        if data.get("code") != "200":
            logger.warning("refresh failed, re-fetching: %s", data)
            self._fetch_token()
            return
        token_data = data["data"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._expires_at = time.time() + int(token_data.get("expires_in", 7199))

    def get_access_token(self) -> str:
        # 过期前 5 分钟 refresh
        if self._access_token is None or time.time() > self._expires_at - 300:
            if self._access_token is None:
                self._fetch_token()
            else:
                self._refresh()
        return self._access_token
