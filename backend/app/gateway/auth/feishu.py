"""Feishu (Lark) OAuth 2.0 client for DeerFlow authentication."""

import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Feishu Open API endpoints
AUTH_URI = "/open-apis/authen/v1/authorize"
USER_ACCESS_TOKEN_URI = "/open-apis/authen/v1/oidc/access_token"
APP_ACCESS_TOKEN_URI = "/open-apis/auth/v3/app_access_token/internal"
USER_INFO_URI = "/open-apis/authen/v1/user_info"


class FeishuAuthError(Exception):
    """Raised when a Feishu API call fails."""

    def __init__(self, code: int = 0, msg: str | None = None):
        self.code = code
        self.msg = msg

    def __str__(self) -> str:
        return f"{self.code}: {self.msg}"


class FeishuOAuthClient:
    """Async Feishu OAuth client using httpx."""

    def __init__(self, lark_host: str, app_id: str, app_secret: str):
        self.lark_host = lark_host.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        """Build the Feishu authorization URL for the user to visit."""
        params = {
            "app_id": self.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
        }
        if state:
            params["state"] = state
        return f"{self.lark_host}{AUTH_URI}?{urlencode(params)}"

    async def _get_app_access_token(self) -> str:
        """Get an app_access_token from Feishu."""
        url = f"{self.lark_host}{APP_ACCESS_TOKEN_URI}"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            _check_feishu_response(data)
            return data["app_access_token"]

    async def get_user_access_token(self, code: str) -> str:
        """Exchange an authorization code for a user_access_token."""
        app_token = await self._get_app_access_token()
        url = f"{self.lark_host}{USER_ACCESS_TOKEN_URI}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {app_token}",
        }
        payload = {"grant_type": "authorization_code", "code": code}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            _check_feishu_response(data)
            return data["data"]["access_token"]

    async def get_user_info(self, user_access_token: str) -> dict:
        """Fetch user profile using a user_access_token."""
        url = f"{self.lark_host}{USER_INFO_URI}"
        headers = {
            "Authorization": f"Bearer {user_access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            _check_feishu_response(data)
            return data["data"]

    async def authorize(self, code: str) -> dict:
        """Full OAuth flow: exchange code for token, then fetch user info.

        Returns:
            User info dict with keys like name, en_name, avatar_url, open_id, etc.
        """
        user_token = await self.get_user_access_token(code)
        user_info = await self.get_user_info(user_token)
        logger.info("Feishu OAuth succeeded for user: %s", user_info.get("name", "unknown"))
        return user_info


def _check_feishu_response(data: dict) -> None:
    """Check a Feishu API response for errors."""
    code = data.get("code", -1)
    if code != 0:
        msg = data.get("msg", "unknown error")
        logger.error("Feishu API error: code=%s, msg=%s", code, msg)
        raise FeishuAuthError(code=code, msg=msg)
