"""OAuth token support for MCP HTTP/SSE servers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig
from deerflow.mcp.credentials import McpUserCredentials, resolve_mcp_user_id, resolve_server_credentials

logger = logging.getLogger(__name__)


@dataclass
class _OAuthToken:
    """Cached OAuth token."""

    access_token: str
    token_type: str
    expires_at: datetime


class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers."""

    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]):
        self._oauth_by_server = oauth_by_server
        self._tokens: dict[tuple[str, str, int], _OAuthToken] = {}
        self._locks: dict[tuple[str, str, int], asyncio.Lock] = {}

    @classmethod
    def from_extensions_config(cls, extensions_config: ExtensionsConfig) -> OAuthTokenManager:
        oauth_by_server: dict[str, McpOAuthConfig] = {}
        for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
            if server_config.oauth and server_config.oauth.enabled:
                oauth_by_server[server_name] = server_config.oauth
        return cls(oauth_by_server)

    def has_oauth_servers(self) -> bool:
        return bool(self._oauth_by_server)

    def oauth_server_names(self) -> list[str]:
        return list(self._oauth_by_server.keys())

    async def get_authorization_header(
        self,
        server_name: str,
        *,
        user_id: str = "default",
        credentials: McpUserCredentials | None = None,
    ) -> str | None:
        oauth = credentials.oauth if credentials is not None and credentials.oauth is not None else self._oauth_by_server.get(server_name)
        if not oauth:
            return None

        key = (server_name, user_id, credentials.version if credentials is not None else 0)
        token = self._tokens.get(key)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            token = self._tokens.get(key)
            if token and not self._is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"

            fresh = await self._fetch_token(oauth)
            self._tokens[key] = fresh
            logger.info("Refreshed OAuth access token for MCP server: %s user=%s", server_name, user_id)
            return f"{fresh.token_type} {fresh.access_token}"

    @staticmethod
    def _is_expiring(token: _OAuthToken, oauth: McpOAuthConfig) -> bool:
        now = datetime.now(UTC)
        return token.expires_at <= now + timedelta(seconds=max(oauth.refresh_skew_seconds, 0))

    async def _fetch_token(self, oauth: McpOAuthConfig) -> _OAuthToken:
        import httpx  # pyright: ignore[reportMissingImports]

        data: dict[str, str] = {
            "grant_type": oauth.grant_type,
            **oauth.extra_token_params,
        }

        if oauth.scope:
            data["scope"] = oauth.scope
        if oauth.audience:
            data["audience"] = oauth.audience

        if oauth.grant_type == "client_credentials":
            if not oauth.client_id or not oauth.client_secret:
                raise ValueError("OAuth client_credentials requires client_id and client_secret")
            data["client_id"] = oauth.client_id
            data["client_secret"] = oauth.client_secret
        elif oauth.grant_type == "refresh_token":
            if not oauth.refresh_token:
                raise ValueError("OAuth refresh_token grant requires refresh_token")
            data["refresh_token"] = oauth.refresh_token
            if oauth.client_id:
                data["client_id"] = oauth.client_id
            if oauth.client_secret:
                data["client_secret"] = oauth.client_secret
        else:
            raise ValueError(f"Unsupported OAuth grant type: {oauth.grant_type}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(oauth.token_url, data=data)
            response.raise_for_status()
            payload = response.json()

        access_token = payload.get(oauth.token_field)
        if not access_token:
            raise ValueError(f"OAuth token response missing '{oauth.token_field}'")

        token_type = str(payload.get(oauth.token_type_field, oauth.default_token_type) or oauth.default_token_type)

        expires_in_raw = payload.get(oauth.expires_in_field, 3600)
        try:
            expires_in = int(expires_in_raw)
        except (TypeError, ValueError):
            expires_in = 3600

        expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in, 1))
        return _OAuthToken(access_token=access_token, token_type=token_type, expires_at=expires_at)


def build_oauth_tool_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    """Build a tool interceptor that injects OAuth Authorization headers."""
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
    enabled_servers = extensions_config.get_enabled_mcp_servers()
    if not token_manager.has_oauth_servers() and not enabled_servers:
        return None

    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        server_config = enabled_servers.get(request.server_name)
        user_id = resolve_mcp_user_id(getattr(request, "runtime", None))
        credentials = None
        if server_config is not None:
            credentials = await resolve_server_credentials(
                request.server_name,
                server_config,
                user_id=user_id,
                include_global_secrets=True,
            )
        header = await token_manager.get_authorization_header(
            request.server_name,
            user_id=user_id,
            credentials=credentials,
        )
        if not header:
            return await handler(request)

        updated_headers = dict(request.headers or {})
        updated_headers["Authorization"] = header
        return await handler(request.override(headers=updated_headers))

    return oauth_interceptor


async def get_initial_oauth_headers(
    extensions_config: ExtensionsConfig,
    *,
    user_id: str | None = None,
) -> dict[str, str]:
    """Get initial OAuth Authorization headers for MCP server connections."""
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
    enabled_servers = extensions_config.get_enabled_mcp_servers()
    if not token_manager.has_oauth_servers() and user_id is None:
        return {}

    headers: dict[str, str] = {}
    server_names = list(enabled_servers) if user_id is not None else token_manager.oauth_server_names()
    for server_name in server_names:
        credentials = None
        if user_id is not None and server_name in enabled_servers:
            credentials = await resolve_server_credentials(
                server_name,
                enabled_servers[server_name],
                user_id=user_id,
                include_global_secrets=True,
            )
        headers[server_name] = await token_manager.get_authorization_header(
            server_name,
            user_id=user_id or "default",
            credentials=credentials,
        ) or ""

    return {name: value for name, value in headers.items() if value}
