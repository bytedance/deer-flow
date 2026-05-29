"""Xiaoshouyi (销售易) OAuth2 token manager.

Manages token lifecycle: acquire, cache, and refresh before expiry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Refresh token 5 minutes before expiry
_REFRESH_MARGIN_SECONDS = 300


class XsyTokenManager:
    """OAuth2 token manager for Xiaoshouyi CRM.

    Credentials are resolved from:
    1. extra_config dict (client_id, client_secret, username, password)
    2. Environment variables (XSY_CLIENT_ID, XSY_CLIENT_SECRET, XSY_USERNAME, XSY_PASSWORD)
    """

    def __init__(
        self,
        auth_url: str = "https://login.xiaoshouyi.com/auc/oauth2/token",
        extra_config: dict[str, Any] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._auth_url = auth_url
        self._extra_config = extra_config or {}
        self._timeout = timeout_seconds
        self._lock = asyncio.Lock()

        # Cached token state
        self._access_token: str | None = None
        self._token_type: str = "Bearer"
        self._expires_at: float = 0.0
        self._api_host: str | None = None

    @property
    def api_host(self) -> str | None:
        """API host from last token response (instance_uri)."""
        return self._api_host

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed.

        Returns:
            Valid access_token string

        Raises:
            IntegrationAuthError: If token acquisition fails
        """
        async with self._lock:
            now = time.time()
            if self._access_token and now < (self._expires_at - _REFRESH_MARGIN_SECONDS):
                return self._access_token

            # Need to refresh
            await self._acquire_token()
            return self._access_token  # type: ignore[return-value]

    async def _acquire_token(self) -> None:
        """Acquire new token via OAuth2 password grant."""
        from deerflow.integrations.errors import IntegrationAuthError

        client_id = self._resolve_credential("client_id", "XSY_CLIENT_ID")
        client_secret = self._resolve_credential("client_secret", "XSY_CLIENT_SECRET")
        username = self._resolve_credential("username", "XSY_USERNAME")
        password = self._resolve_credential("password", "XSY_PASSWORD")

        if not all([client_id, client_secret, username, password]):
            raise IntegrationAuthError(
                system_key="xsy",
                message="Missing Xiaoshouyi credentials (client_id, client_secret, username, password)",
            )

        payload = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._auth_url, data=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise IntegrationAuthError(
                system_key="xsy",
                message=f"Xiaoshouyi auth failed: HTTP {exc.response.status_code}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise IntegrationAuthError(
                system_key="xsy",
                message=f"Xiaoshouyi auth timeout ({self._timeout}s)",
            ) from exc
        except Exception as exc:
            raise IntegrationAuthError(
                system_key="xsy",
                message=f"Xiaoshouyi auth error: {exc}",
            ) from exc

        # Parse response
        self._access_token = data.get("access_token")
        self._token_type = data.get("token_type", "Bearer")
        expires_in = data.get("expires_in", 86399)
        self._expires_at = time.time() + expires_in

        # Extract API host from instance_uri
        instance_uri = data.get("instance_uri")
        if instance_uri:
            self._api_host = instance_uri

        if not self._access_token:
            raise IntegrationAuthError(
                system_key="xsy",
                message="Xiaoshouyi auth response missing access_token",
            )

        logger.info(
            "Xiaoshouyi token acquired (expires_in=%ss, api_host=%s)",
            expires_in,
            self._api_host,
        )

    def _resolve_credential(self, config_key: str, env_key: str) -> str | None:
        """Resolve credential from extra_config or environment variable."""
        # Try extra_config first
        value = self._extra_config.get(config_key)
        if value:
            # Check if it's an env var reference like "$XSY_CLIENT_ID"
            if isinstance(value, str) and value.startswith("$"):
                return os.environ.get(value[1:])
            return value

        # Try env var name from config
        env_var_name = self._extra_config.get(f"{config_key}_env")
        if env_var_name:
            return os.environ.get(env_var_name)

        # Fall back to standard env var
        return os.environ.get(env_key)

    async def invalidate(self) -> None:
        """Force token refresh on next get_token() call."""
        async with self._lock:
            self._access_token = None
            self._expires_at = 0.0
            logger.info("Xiaoshouyi token invalidated")

    def is_valid(self) -> bool:
        """Check if current token is valid (without refreshing)."""
        if not self._access_token:
            return False
        return time.time() < (self._expires_at - _REFRESH_MARGIN_SECONDS)
